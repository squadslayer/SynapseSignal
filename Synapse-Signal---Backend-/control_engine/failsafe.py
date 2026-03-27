"""
SynapseSignal Control Engine — Failsafe System
================================================
Phase 10: Graceful degradation when upstream data (Dev 2 / Dev 1) is
missing, corrupt, or delayed.

Design:
    No undefined signal states — ever. If the control engine cannot
    produce a computed decision, it MUST emit a safe default cycle.

Failure modes handled:
    1. Missing / stale data   → default cycle
    2. Schema validation fail → 422 (already handled by Pydantic)
    3. Engine exception       → safe fallback with logging
    4. Redis down             → continue without persistence
    5. All sectors scored 0   → round-robin fallback

The failsafe wraps the decision engine's decide() call, catches ALL
exceptions, and guarantees a valid SignalDecisionOutput is always
returned.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

from schemas import (
    IntersectionTrafficState,
    RouteData,
    SignalDecisionOutput,
    SignalState,
    SignalStateEnum,
    TimingInfo,
    FallbackState,
    DecisionMode,
)
from decision_engine import SignalDecisionEngine
from state_manager import IntersectionStateManager

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    FAILSAFE CONFIGURATION                           ║
# ╚═══════════════════════════════════════════════════════════════════════╝

# Default safe cycle: all RED except the first sector, 15s green.
DEFAULT_GREEN_SEC = 15.0
DEFAULT_CYCLE_SEC = 33.0  # 15 green + 15 other + 3 clearance
FALLBACK_SECTOR = "FAILSAFE_DEFAULT"


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                       FAILSAFE WRAPPER                              ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class FailsafeController:
    """
    Wraps the SignalDecisionEngine to guarantee a valid output always.

    Usage:
        controller = FailsafeController(decision_engine, state_manager)
        output = controller.safe_decide(state, route_data)
        # output is ALWAYS a valid SignalDecisionOutput

    Failsafe is transparent: when things work, it passes through
    the engine's output. When things break, it substitutes a safe
    default without crashing.
    """

    def __init__(
        self,
        decision_engine: SignalDecisionEngine,
        state_manager: IntersectionStateManager,
    ) -> None:
        self._engine = decision_engine
        self._state_manager = state_manager
        self._fallback_state: Optional[FallbackState] = None
        self._consecutive_failures: int = 0
        self._total_fallbacks: int = 0

    @property
    def is_in_fallback(self) -> bool:
        return self._fallback_state is not None

    @property
    def fallback_state(self) -> Optional[FallbackState]:
        return self._fallback_state

    @property
    def stats(self) -> dict:
        return {
            "in_fallback": self.is_in_fallback,
            "consecutive_failures": self._consecutive_failures,
            "total_fallbacks": self._total_fallbacks,
            "fallback_reason": (
                self._fallback_state.reason if self._fallback_state else None
            ),
        }

    # ── Main entry ───────────────────────────────────────────────────────

    def safe_decide(
        self,
        state: IntersectionTrafficState,
        route_data: Optional[RouteData] = None,
    ) -> SignalDecisionOutput:
        """
        Execute a control cycle with full failsafe protection.

        Order of checks:
            1. Staleness check: is the data too old?
            2. Try the engine's decide() method.
            3. If any exception, emit safe default.
        """
        iid = state.intersection_id

        # ── Check 1: Staleness ───────────────────────────────────────
        if self._state_manager.is_stale(iid):
            current = self._state_manager.get_current_state(iid)
            if current is not None:
                logger.warning(
                    "⚠️ Stale data for %s — using failsafe default", iid
                )
                return self._emit_failsafe(
                    state, reason=f"stale_data_for_{iid}"
                )

        # ── Check 2: Try normal decision ─────────────────────────────
        try:
            output = self._engine.decide(state, route_data)

            # Success — clear fallback state.
            if self._fallback_state is not None:
                logger.info(
                    "✅ Failsafe cleared for %s — normal operation resumed",
                    iid,
                )
            self._fallback_state = None
            self._consecutive_failures = 0
            return output

        except Exception as exc:
            # ── Check 3: Engine failure → failsafe ───────────────────
            self._consecutive_failures += 1
            self._total_fallbacks += 1
            logger.error(
                "🚨 Decision engine FAILED for %s (attempt #%d): %s\n%s",
                iid,
                self._consecutive_failures,
                str(exc),
                traceback.format_exc(),
            )
            return self._emit_failsafe(
                state, reason=f"engine_exception: {type(exc).__name__}: {exc}"
            )

    # ── Failsafe output ──────────────────────────────────────────────────

    def _emit_failsafe(
        self,
        state: IntersectionTrafficState,
        reason: str,
    ) -> SignalDecisionOutput:
        """
        Build a guaranteed-safe default signal output.

        Strategy:
          • If we have sector info: give GREEN to the first sector.
          • If no sector info: give RED to all lanes (safest default).
          • Always produce a fixed, safe timing cycle.
        """
        self._fallback_state = FallbackState(
            fallback_active=True,
            reason=reason,
            mode="default_cycle",
        )

        # Determine which lanes get green.
        if state.sectors:
            # Give the first sector GREEN.
            first_sector = state.sectors[0]
            green_ids = set(first_sector.lanes)
            selected_sector = first_sector.sector_id
        else:
            # No sectors at all — all RED (safest).
            green_ids = set()
            selected_sector = FALLBACK_SECTOR

        signals = []
        for lane in state.lanes:
            sig_state = (
                SignalStateEnum.GREEN
                if lane.lane_id in green_ids
                else SignalStateEnum.RED
            )
            signals.append(SignalState(lane_id=lane.lane_id, state=sig_state))

        output = SignalDecisionOutput(
            intersection_id=state.intersection_id,
            timestamp=datetime.now(timezone.utc),
            selected_sector=selected_sector,
            signals=signals,
            timing=TimingInfo(
                green_time=DEFAULT_GREEN_SEC,
                cycle_length=DEFAULT_CYCLE_SEC,
            ),
            corridor=None,
        )

        logger.warning(
            "⚠️ FAILSAFE output for %s: sector=%s, reason=%s",
            state.intersection_id, selected_sector, reason,
        )
        return output

    # ── Manual trigger (for testing / ops) ───────────────────────────────

    def force_failsafe(
        self, state: IntersectionTrafficState, reason: str = "manual_trigger"
    ) -> SignalDecisionOutput:
        """Manually trigger failsafe mode (for testing or ops)."""
        self._total_fallbacks += 1
        return self._emit_failsafe(state, reason)

    def clear_failsafe(self) -> None:
        """Manually clear failsafe state."""
        self._fallback_state = None
        self._consecutive_failures = 0
        logger.info("Failsafe state manually cleared")
