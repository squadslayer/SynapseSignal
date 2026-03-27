"""
SynapseSignal Control Engine — Green Corridor Orchestration Engine
===================================================================
Dev 3 Additions: Emergency override, predictive routing, and green
corridor management.

Pipeline:
    1. Route Selection:   Pick optimal route from Dev 2's candidates.
    2. ETA Scheduling:    Pre-compute GREEN windows for each intersection.
    3. Signal Override:   Force GREEN on corridor intersections ahead of
                          the emergency vehicle.
    4. Live Monitoring:   Track vehicle position, detect congestion spikes.
    5. Dynamic Reroute:   Re-select route if conditions change.
    6. Post-Passage:      Restore intersections to normal flow after
                          the vehicle passes.

Design:
    • Deterministic selector: min(estimated_time) weighted by congestion.
    • Pre-emptive greens: schedule GREEN *before* arrival, not on arrival.
    • Stateful: tracks the active corridor lifecycle from activation
      through completion.
    • Integrates with Dev 5 Redis (corridor:active) and PostgreSQL
      (corridor_logs, routes, route_nodes).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from schemas import (
    Route,
    RouteData,
    EmergencyState,
    IntersectionTrafficState,
    CorridorState,
    CorridorStatus,
    ETAEntry,
    SignalDecisionOutput,
    SignalState,
    SignalStateEnum,
    TimingInfo,
)

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                        CONFIGURATION                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@dataclass(frozen=True)
class CorridorConfig:
    """Tunable parameters for the corridor engine."""

    # How much congestion matters vs. raw time in route scoring.
    # score = estimated_time × (1 + congestion_weight × avg_congestion)
    congestion_weight: float = 0.5

    # Seconds of green to hold *before* the vehicle arrives.
    pre_arrival_buffer_sec: float = 5.0

    # How long each corridor green phase lasts.
    corridor_green_duration_sec: float = 20.0

    # Threshold of avg_congestion increase to trigger reroute.
    reroute_congestion_threshold: float = 0.3

    # After the vehicle passes an intersection, how many seconds
    # before we start restoring normal flow.
    restoration_delay_sec: float = 3.0

    # Default cycle during restoration (gentle transition back).
    restoration_green_sec: float = 10.0


DEFAULT_CORRIDOR_CONFIG = CorridorConfig()


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                     CORRIDOR LIFECYCLE                               ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class CorridorPhase(str, Enum):
    """Internal lifecycle phases of a green corridor."""
    IDLE = "idle"
    ROUTE_SELECTED = "route_selected"
    SCHEDULING = "scheduling"
    ACTIVE = "active"
    REROUTING = "rerouting"
    RESTORING = "restoring"
    COMPLETED = "completed"


@dataclass
class CorridorSession:
    """
    Tracks the full lifecycle of one emergency corridor event.

    Created when an emergency is detected, destroyed when the vehicle
    reaches its destination or the emergency is deactivated.
    """
    # Identity
    emergency_vehicle_id: str
    vehicle_type: str

    # Route
    selected_route: Optional[Route] = None
    route_intersections: list[str] = field(default_factory=list)

    # Scheduling
    eta_sequence: list[ETAEntry] = field(default_factory=list)

    # Position tracking
    current_intersection_idx: int = 0
    passed_intersections: list[str] = field(default_factory=list)

    # Lifecycle
    phase: CorridorPhase = CorridorPhase.IDLE
    activated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Restoration queue: intersections waiting to return to normal.
    restoration_queue: list[str] = field(default_factory=list)

    @property
    def current_intersection(self) -> Optional[str]:
        if 0 <= self.current_intersection_idx < len(self.route_intersections):
            return self.route_intersections[self.current_intersection_idx]
        return None

    @property
    def next_intersection(self) -> Optional[str]:
        nxt = self.current_intersection_idx + 1
        if nxt < len(self.route_intersections):
            return self.route_intersections[nxt]
        return None

    @property
    def upcoming_intersections(self) -> list[str]:
        """Intersections the vehicle hasn't reached yet."""
        return self.route_intersections[self.current_intersection_idx:]

    @property
    def is_active(self) -> bool:
        return self.phase in (
            CorridorPhase.ROUTE_SELECTED,
            CorridorPhase.SCHEDULING,
            CorridorPhase.ACTIVE,
            CorridorPhase.REROUTING,
            CorridorPhase.RESTORING,
        )


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   ROUTE SELECTION ENGINE                             ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def score_route(
    route: Route,
    config: CorridorConfig = DEFAULT_CORRIDOR_CONFIG,
) -> float:
    """
    Score a candidate route. Lower is better.

    Formula:
        score = estimated_time × (1 + congestion_weight × avg_congestion)

    This penalises routes that are fast but congested (risk of delay),
    and rewards routes that are both fast AND clear.
    """
    return route.estimated_time * (
        1.0 + config.congestion_weight * route.avg_congestion
    )


def select_best_route(
    route_data: RouteData,
    config: CorridorConfig = DEFAULT_CORRIDOR_CONFIG,
) -> Optional[Route]:
    """
    Deterministically select the best route from Dev 2's candidates.

    Returns the route with the lowest score (min estimated_time
    weighted by congestion). Returns None if no routes available.
    """
    if not route_data.routes:
        logger.warning("No routes available for corridor selection")
        return None

    scored = [(score_route(r, config), r) for r in route_data.routes]
    scored.sort(key=lambda x: x[0])

    best_score, best_route = scored[0]
    logger.info(
        "Selected route %s (score=%.2f, time=%.1fs, congestion=%.2f, "
        "hops=%d)",
        best_route.route_id, best_score, best_route.estimated_time,
        best_route.avg_congestion, len(best_route.path),
    )
    return best_route


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  PREDICTIVE ETA SCHEDULING                           ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def compute_eta_schedule(
    route: Route,
    config: CorridorConfig = DEFAULT_CORRIDOR_CONFIG,
) -> list[ETAEntry]:
    """
    Compute the predicted GREEN window for each intersection on the route.

    Strategy:
        • Divide total estimated_time evenly across hops.
        • Schedule green to start `pre_arrival_buffer_sec` before the
          predicted arrival (so the light is already green when the
          vehicle arrives).
        • Each green lasts `corridor_green_duration_sec`.

    Returns:
        Ordered list of ETAEntry (one per intersection in the path).
    """
    n_intersections = len(route.path)
    if n_intersections == 0:
        return []

    # Time between consecutive intersections (uniform distribution).
    if n_intersections > 1:
        hop_time = route.estimated_time / (n_intersections - 1)
    else:
        hop_time = 0.0

    entries: list[ETAEntry] = []
    for i, intersection_id in enumerate(route.path):
        # Predicted arrival time offset from start (seconds).
        arrival_offset = i * hop_time

        # Green should start *before* arrival.
        green_start = max(0.0, arrival_offset - config.pre_arrival_buffer_sec)

        entries.append(ETAEntry(
            intersection_id=intersection_id,
            green_start=round(green_start, 1),
            green_duration=config.corridor_green_duration_sec,
        ))

    logger.debug(
        "ETA schedule for route %s: %s",
        route.route_id,
        [(e.intersection_id, e.green_start) for e in entries],
    )
    return entries


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                 GREEN CORRIDOR ORCHESTRATOR                          ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class GreenCorridorEngine:
    """
    Orchestrates the full green corridor lifecycle.

    Usage:
        engine = GreenCorridorEngine()
        engine.activate(emergency_state, route_data)  # start corridor
        output = engine.get_corridor_override(intersection_id)
        engine.update_position(new_intersection_idx)
        engine.check_reroute(route_data)
        engine.deactivate()  # emergency over
    """

    def __init__(
        self, config: CorridorConfig = DEFAULT_CORRIDOR_CONFIG
    ) -> None:
        self._config = config
        self._session: Optional[CorridorSession] = None
        self._corridor_log: list[dict] = []

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self._session is not None and self._session.is_active

    @property
    def session(self) -> Optional[CorridorSession]:
        return self._session

    # ── Activation ───────────────────────────────────────────────────────

    def activate(
        self,
        emergency: EmergencyState,
        route_data: RouteData,
    ) -> Optional[CorridorSession]:
        """
        Activate a green corridor for an emergency vehicle.

        Steps:
            1. Select the best route.
            2. Compute ETA schedule.
            3. Transition to ACTIVE phase.

        Returns the CorridorSession or None if activation failed.
        """
        if not emergency.active:
            logger.debug("Emergency not active — skipping corridor activation")
            return None

        # Select route
        best_route = select_best_route(route_data, self._config)
        if best_route is None:
            logger.warning("Cannot activate corridor: no viable routes")
            return None

        # Compute ETAs
        eta_schedule = compute_eta_schedule(best_route, self._config)

        # Create session
        self._session = CorridorSession(
            emergency_vehicle_id=emergency.vehicle_id or "UNKNOWN",
            vehicle_type=(
                emergency.vehicle_type.value if emergency.vehicle_type else "unknown"
            ),
            selected_route=best_route,
            route_intersections=list(best_route.path),
            eta_sequence=eta_schedule,
            current_intersection_idx=0,
            phase=CorridorPhase.ACTIVE,
            activated_at=datetime.now(timezone.utc),
        )

        logger.info(
            "🚨 Green corridor ACTIVATED for %s (%s) on route %s: %s",
            self._session.emergency_vehicle_id,
            self._session.vehicle_type,
            best_route.route_id,
            " → ".join(best_route.path),
        )
        return self._session

    # ── Override signal for a specific intersection ──────────────────────

    def get_corridor_override(
        self, intersection_id: str
    ) -> Optional[SignalDecisionOutput]:
        """
        Check if this intersection should be overridden for the corridor.

        Returns a SignalDecisionOutput with emergency GREEN if the
        intersection is in the upcoming path, None otherwise.

        The caller (decision engine) should use this output INSTEAD of
        the normal flow-based decision when it returns non-None.
        """
        if not self.is_active or self._session is None:
            return None

        session = self._session
        upcoming = set(session.upcoming_intersections)

        if intersection_id not in upcoming:
            # Check if it's in the restoration queue
            if intersection_id in session.restoration_queue:
                return None  # Let normal flow handle restoration
            return None

        # Find the ETA entry for this intersection.
        eta = next(
            (e for e in session.eta_sequence
             if e.intersection_id == intersection_id),
            None,
        )

        # Build the corridor state for Dev 4 visualization.
        corridor_state = CorridorState(
            route=session.route_intersections,
            active_corridor=list(upcoming),
            current_intersection=session.current_intersection or intersection_id,
            eta_sequence=session.eta_sequence,
            status=CorridorStatus.ACTIVE,
        )

        green_duration = (
            eta.green_duration if eta
            else self._config.corridor_green_duration_sec
        )

        return SignalDecisionOutput(
            intersection_id=intersection_id,
            timestamp=datetime.now(timezone.utc),
            selected_sector="EMERGENCY_CORRIDOR",
            signals=[],  # Populated by the decision engine with all-green for corridor lane
            timing=TimingInfo(
                green_time=green_duration,
                cycle_length=green_duration + self._config.restoration_green_sec,
            ),
            corridor=corridor_state,
        )

    # ── Position tracking ────────────────────────────────────────────────

    def update_position(self, new_intersection_idx: int) -> None:
        """
        Update the vehicle's current position along the corridor.

        When the vehicle advances past an intersection:
          1. Mark old intersection as passed.
          2. Add it to the restoration queue.
          3. Advance the pointer.
        """
        if self._session is None:
            return

        session = self._session
        old_idx = session.current_intersection_idx

        if new_intersection_idx <= old_idx:
            return  # No forward progress

        # Mark passed intersections for restoration.
        for i in range(old_idx, min(new_intersection_idx, len(session.route_intersections))):
            passed_id = session.route_intersections[i]
            if passed_id not in session.passed_intersections:
                session.passed_intersections.append(passed_id)
                session.restoration_queue.append(passed_id)
                logger.info(
                    "Vehicle passed %s — queued for restoration", passed_id
                )

                # Log for Dev 5 PostgreSQL
                self._corridor_log.append({
                    "intersection_id": passed_id,
                    "green_start": session.activated_at,
                    "green_end": datetime.now(timezone.utc),
                    "route_id": (
                        session.selected_route.route_id
                        if session.selected_route else None
                    ),
                })

        session.current_intersection_idx = new_intersection_idx

        # Check if corridor is complete
        if new_intersection_idx >= len(session.route_intersections):
            self._complete_corridor()

    def advance_by_intersection_id(self, intersection_id: str) -> None:
        """Advance the position to a specific intersection by ID."""
        if self._session is None:
            return
        try:
            idx = self._session.route_intersections.index(intersection_id)
            self.update_position(idx + 1)  # +1 because we've passed it
        except ValueError:
            logger.warning(
                "Intersection %s not found in corridor route", intersection_id
            )

    # ── Dynamic rerouting ────────────────────────────────────────────────

    def check_reroute(
        self, route_data: RouteData
    ) -> bool:
        """
        Check if the corridor should be rerouted due to congestion changes.

        Triggers reroute if:
          • A better route exists with significantly lower score.
          • The current route's congestion has spiked above threshold.

        Returns True if a reroute occurred.
        """
        if self._session is None or not self.is_active:
            return False

        session = self._session
        if session.selected_route is None:
            return False

        # Score the current route
        current_score = score_route(session.selected_route, self._config)

        # Score all alternatives
        best_alt = select_best_route(route_data, self._config)
        if best_alt is None:
            return False

        alt_score = score_route(best_alt, self._config)

        # Only reroute if the alternative is significantly better
        improvement = (current_score - alt_score) / current_score
        if improvement > self._config.reroute_congestion_threshold:
            logger.info(
                "🔄 REROUTING corridor: %s → %s (improvement=%.1f%%)",
                session.selected_route.route_id,
                best_alt.route_id,
                improvement * 100,
            )

            # Add remaining upcoming intersections to restoration
            for iid in session.upcoming_intersections:
                if iid not in session.restoration_queue:
                    session.restoration_queue.append(iid)

            # Switch to new route
            session.selected_route = best_alt
            session.route_intersections = list(best_alt.path)
            session.eta_sequence = compute_eta_schedule(
                best_alt, self._config
            )
            session.current_intersection_idx = 0
            session.phase = CorridorPhase.ACTIVE

            return True

        return False

    # ── Post-passage restoration ─────────────────────────────────────────

    def get_restoration_intersections(self) -> list[str]:
        """
        Return intersections that have been passed and need restoration.

        The caller should gradually transition these back to normal
        flow-based control rather than snapping them back instantly.
        """
        if self._session is None:
            return []
        return list(self._session.restoration_queue)

    def mark_restored(self, intersection_id: str) -> None:
        """Mark an intersection as successfully restored to normal flow."""
        if self._session is not None:
            try:
                self._session.restoration_queue.remove(intersection_id)
                logger.debug("Intersection %s restored to normal", intersection_id)
            except ValueError:
                pass

    # ── Deactivation ─────────────────────────────────────────────────────

    def deactivate(self) -> None:
        """
        Manually deactivate the corridor (e.g., emergency cancelled).

        All remaining intersections are queued for restoration.
        """
        if self._session is None:
            return

        session = self._session
        # Queue all remaining intersections for restoration.
        for iid in session.upcoming_intersections:
            if iid not in session.restoration_queue:
                session.restoration_queue.append(iid)

        session.phase = CorridorPhase.RESTORING
        logger.info("Green corridor DEACTIVATED — restoring %d intersections",
                     len(session.restoration_queue))

    def _complete_corridor(self) -> None:
        """Mark the corridor as completed (vehicle reached destination)."""
        if self._session is None:
            return

        self._session.phase = CorridorPhase.COMPLETED
        self._session.completed_at = datetime.now(timezone.utc)
        logger.info(
            "🏁 Green corridor COMPLETED for %s",
            self._session.emergency_vehicle_id,
        )

    # ── Redis / Dev 5 data accessors ─────────────────────────────────────

    def get_redis_corridor_data(self) -> Optional[dict]:
        """
        Build the corridor:active payload for Redis (Dev 5).

        Returns None if no active corridor.
        """
        if self._session is None or not self.is_active:
            return None

        session = self._session
        return {
            "route": session.route_intersections,
            "current_position": session.current_intersection or "",
            "next_intersection": session.next_intersection or "",
            "vehicle_id": session.emergency_vehicle_id,
            "vehicle_type": session.vehicle_type,
            "status": session.phase.value,
        }

    def get_corridor_log_entries(self) -> list[dict]:
        """
        Return corridor log entries for Dev 5 PostgreSQL insertion.

        Each entry maps to a row in the `corridor_logs` table.
        Clears the internal log after retrieval.
        """
        entries = list(self._corridor_log)
        self._corridor_log.clear()
        return entries

    def get_route_entry(self) -> Optional[dict]:
        """
        Return route data for Dev 5 PostgreSQL `routes` table.

        Returns None if no active session with a selected route.
        """
        if self._session is None or self._session.selected_route is None:
            return None

        route = self._session.selected_route
        return {
            "route_id": route.route_id,
            "total_distance": route.total_distance,
            "estimated_time": route.estimated_time,
            "path": route.path,
        }

    def get_corridor_output_state(self) -> Optional[CorridorState]:
        """
        Build the CorridorState for Dev 4's SignalDecisionOutput.

        Returns None if no active corridor.
        """
        if self._session is None or not self.is_active:
            return None

        session = self._session
        status = CorridorStatus.ACTIVE
        if session.phase == CorridorPhase.REROUTING:
            status = CorridorStatus.REPLANNED
        elif session.phase == CorridorPhase.COMPLETED:
            status = CorridorStatus.COMPLETED

        return CorridorState(
            route=session.route_intersections,
            active_corridor=session.upcoming_intersections,
            current_intersection=session.current_intersection or "",
            eta_sequence=session.eta_sequence,
            status=status,
        )
