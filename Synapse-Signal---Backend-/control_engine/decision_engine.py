"""
SynapseSignal Control Engine — Signal Decision Engine
======================================================
Final signal actuation — the "brain" that produces executable
traffic light commands.

Priority hierarchy (enforced in decide()):
    1. Emergency Override  (corridor engine)
    2. City Strategy       (future phase)
    3. Local Flow Logic    (flow engine)

Safety guarantees:
  • No two conflicting sectors can have GREEN simultaneously.
  • Emergency override always takes precedence.
  • Deterministic: identical input → identical output.
  • Fallback: if computation fails, emit a safe default cycle.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from schemas import (
    IntersectionTrafficState,
    RouteData,
    SignalDecisionOutput,
    SignalState,
    SignalStateEnum,
    TimingInfo,
    FlowScore,
    SectorScore,
    ControlDecision,
    DecisionMode,
    DecisionLog,
)
from flow_engine import (
    compute_all_lane_flow_scores,
    compute_sector_scores,
    select_best_sector,
)
from timing_controller import (
    build_timing_info,
    TimingParams,
    DEFAULT_TIMING,
)
from state_manager import IntersectionStateManager
from corridor_engine import GreenCorridorEngine

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    SIGNAL DECISION ENGINE                            ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class SignalDecisionEngine:
    """
    Orchestrates one complete control cycle for an intersection.

    Usage:
        engine = SignalDecisionEngine(state_manager, corridor_engine)
        output = engine.decide(traffic_state)
        # For emergency+routing:
        output = engine.decide(traffic_state, route_data=route_data)

    The engine is stateless per call — all temporal context lives in
    the IntersectionStateManager and GreenCorridorEngine.
    """

    def __init__(
        self,
        state_manager: IntersectionStateManager,
        timing_params: TimingParams = DEFAULT_TIMING,
        corridor_engine: Optional[GreenCorridorEngine] = None,
    ) -> None:
        self._state_manager = state_manager
        self._timing_params = timing_params
        self._corridor_engine = corridor_engine or GreenCorridorEngine()
        self._decision_log: list[DecisionLog] = []

    @property
    def corridor_engine(self) -> GreenCorridorEngine:
        """Expose the corridor engine for direct access (API routes)."""
        return self._corridor_engine

    # ── Main entry point ─────────────────────────────────────────────────

    def decide(
        self,
        state: IntersectionTrafficState,
        route_data: Optional[RouteData] = None,
    ) -> SignalDecisionOutput:
        """
        Execute a full control cycle and return signal commands.

        Priority:
            1. Emergency override (if emergency active + corridor engine)
            2. Normal flow-based decision

        Args:
            state:      Validated traffic state from Dev 2.
            route_data: Optional route candidates from Dev 2 (for emergency).

        Returns:
            SignalDecisionOutput aligned with the Dev 4 contract.
        """
        iid = state.intersection_id

        # ── Priority 1: Emergency Override ───────────────────────────────
        if state.emergency_state.active:
            emergency_output = self._handle_emergency(
                state, route_data
            )
            if emergency_output is not None:
                return emergency_output

        # ── Priority 2: Check if corridor override applies ───────────────
        if self._corridor_engine.is_active:
            corridor_output = self._corridor_engine.get_corridor_override(iid)
            if corridor_output is not None:
                # Fill in per-lane signals (all GREEN for this intersection)
                corridor_output.signals = self._assign_all_green(state)
                self._log_decision_entry(
                    state, [], [], DecisionMode.EMERGENCY_OVERRIDE,
                    "EMERGENCY_CORRIDOR",
                    "corridor_override_active",
                )
                logger.info(
                    "🚨 EMERGENCY OVERRIDE for %s — all GREEN (corridor)",
                    iid,
                )
                return corridor_output

        # ── Priority 3: Normal Flow Logic ────────────────────────────────
        return self._decide_normal(state)

    # ── Emergency handling ───────────────────────────────────────────────

    def _handle_emergency(
        self,
        state: IntersectionTrafficState,
        route_data: Optional[RouteData],
    ) -> Optional[SignalDecisionOutput]:
        """
        Activate or update the green corridor for an emergency.

        If corridor is not yet active and route_data is available,
        activate it. If already active, check for reroute.

        Returns an override output if this intersection is on the
        corridor path, None otherwise (fall through to normal logic).
        """
        corridor = self._corridor_engine

        # Activate corridor if not already active
        if not corridor.is_active and route_data is not None:
            session = corridor.activate(
                state.emergency_state, route_data
            )
            if session is not None:
                logger.info(
                    "Emergency corridor activated: %s",
                    " → ".join(session.route_intersections),
                )
            else:
                # Activation failed (no routes) — fall through to normal
                return None

        # If active, check for reroute with new data
        if corridor.is_active and route_data is not None:
            corridor.check_reroute(route_data)

        # Check if THIS intersection needs an override
        override = corridor.get_corridor_override(state.intersection_id)
        if override is not None:
            override.signals = self._assign_all_green(state)
            self._log_decision_entry(
                state, [], [], DecisionMode.EMERGENCY_OVERRIDE,
                "EMERGENCY_CORRIDOR",
                f"emergency_vehicle={state.emergency_state.vehicle_id}",
            )
            return override

        return None

    # ── Normal flow decision ─────────────────────────────────────────────

    def _decide_normal(
        self, state: IntersectionTrafficState
    ) -> SignalDecisionOutput:
        """Normal flow-based decision (non-emergency path)."""
        iid = state.intersection_id

        # 1. Lane flow scores
        lane_scores = compute_all_lane_flow_scores(state)

        # 2. Sector scores
        sector_scores = compute_sector_scores(state.sectors, lane_scores)

        # 3. Select best sector (with dwell-time check)
        selected = self._select_sector_with_dwell(iid, sector_scores)

        if selected is None:
            logger.error(
                "No sector could be selected for %s — using fallback", iid,
            )
            return self._build_fallback_output(state)

        # 4. Assign signal states
        signals = self._assign_signals(state, selected.sector_id)

        # 5. Adaptive timing
        timing = build_timing_info(selected, state, self._timing_params)

        # 6. Attach corridor state if active (for Dev 4 map overlay)
        corridor_state = self._corridor_engine.get_corridor_output_state()

        # 7. Build output
        output = SignalDecisionOutput(
            intersection_id=iid,
            timestamp=datetime.now(timezone.utc),
            selected_sector=selected.sector_id,
            signals=signals,
            timing=timing,
            corridor=corridor_state,
        )

        # 8. Update state manager
        self._state_manager.set_active_sector(iid, selected.sector_id)

        # 9. Log decision
        self._log_decision_entry(
            state, lane_scores, sector_scores, DecisionMode.NORMAL,
            selected.sector_id,
            f"highest_flow_score={selected.sector_score:.4f}",
        )

        logger.info(
            "Decision for %s: sector=%s (score=%.4f), "
            "green=%.1fs, cycle=%.1fs",
            iid, selected.sector_id, selected.sector_score,
            timing.green_time, timing.cycle_length,
        )

        return output

    # ── Sector selection with dwell-time ─────────────────────────────────

    def _select_sector_with_dwell(
        self,
        intersection_id: str,
        sector_scores: list[SectorScore],
    ) -> Optional[SectorScore]:
        """Select the best sector, respecting the minimum dwell time."""
        if not sector_scores:
            return None

        best = sector_scores[0]

        if self._state_manager.can_switch_sector(
            intersection_id, best.sector_id
        ):
            return best

        current_sector_id = self._get_current_sector(intersection_id)
        if current_sector_id:
            for ss in sector_scores:
                if ss.sector_id == current_sector_id and ss.sector_score > 0:
                    return ss

        return best

    def _get_current_sector(
        self, intersection_id: str
    ) -> Optional[str]:
        record = self._state_manager._records.get(intersection_id)
        if record:
            return record.active_sector
        return None

    # ── Signal assignment ────────────────────────────────────────────────

    def _assign_signals(
        self,
        state: IntersectionTrafficState,
        selected_sector_id: str,
    ) -> list[SignalState]:
        """Assign GREEN to selected sector lanes, RED to others."""
        green_lane_ids: set[str] = set()
        for sector in state.sectors:
            if sector.sector_id == selected_sector_id:
                green_lane_ids.update(sector.lanes)
                break

        signals: list[SignalState] = []
        for lane in state.lanes:
            if lane.lane_id in green_lane_ids:
                signals.append(
                    SignalState(lane_id=lane.lane_id, state=SignalStateEnum.GREEN)
                )
            else:
                signals.append(
                    SignalState(lane_id=lane.lane_id, state=SignalStateEnum.RED)
                )
        return signals

    def _assign_all_green(
        self, state: IntersectionTrafficState
    ) -> list[SignalState]:
        """
        Assign GREEN to ALL lanes (emergency corridor override).

        During an emergency, the intersection goes all-green on the
        corridor path to clear the way.
        """
        return [
            SignalState(lane_id=lane.lane_id, state=SignalStateEnum.GREEN)
            for lane in state.lanes
        ]

    # ── Fallback output ──────────────────────────────────────────────────

    def _build_fallback_output(
        self, state: IntersectionTrafficState
    ) -> SignalDecisionOutput:
        fallback_sector = (
            state.sectors[0].sector_id if state.sectors else "UNKNOWN"
        )
        signals = self._assign_signals(state, fallback_sector)
        return SignalDecisionOutput(
            intersection_id=state.intersection_id,
            timestamp=datetime.now(timezone.utc),
            selected_sector=fallback_sector,
            signals=signals,
            timing=TimingInfo(
                green_time=self._timing_params.base_green_sec,
                cycle_length=self._timing_params.base_green_sec * 2
                             + self._timing_params.inter_phase_sec,
            ),
            corridor=None,
        )

    # ── Decision logging ─────────────────────────────────────────────────

    def _log_decision_entry(
        self,
        state: IntersectionTrafficState,
        lane_scores: list[FlowScore],
        sector_scores: list[SectorScore],
        mode: DecisionMode,
        selected_sector: str,
        reason: str,
    ) -> None:
        decision = ControlDecision(
            mode=mode,
            selected_sector=selected_sector,
            reason=reason,
            flow_scores=lane_scores,
            sector_scores=sector_scores,
        )
        entry = DecisionLog(
            timestamp=datetime.now(timezone.utc),
            input=state,
            flow_scores=lane_scores,
            sector_scores=sector_scores,
            decision=decision,
            reason=reason,
        )
        self._decision_log.append(entry)
        if len(self._decision_log) > 1000:
            self._decision_log = self._decision_log[-500:]

    def get_recent_decisions(
        self, count: int = 10
    ) -> list[DecisionLog]:
        """Return the N most recent decision logs."""
        return self._decision_log[-count:]

