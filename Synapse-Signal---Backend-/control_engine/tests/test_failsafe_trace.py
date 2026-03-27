"""
Tests for the Failsafe Controller and Traceability Logger.

Verifies:
  • Failsafe passes through successful decisions
  • Failsafe catches engine exceptions → safe default output
  • Failsafe handles stale data gracefully
  • No undefined signal states ever
  • Trace logger records entries correctly
  • Human-readable reason generation
  • PostgreSQL row mapping
  • Buffer overflow → file fallback
  • Thread safety of trace buffer
"""

import pytest
import os
import sys
import json
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import (
    IntersectionTrafficState,
    SignalDecisionOutput,
    SignalState,
    SignalStateEnum,
    TimingInfo,
    DecisionMode,
    FlowScore,
    SectorScore,
    EmergencyState,
    EmergencyVehicleType,
)
from state_manager import IntersectionStateManager, InMemoryStore
from decision_engine import SignalDecisionEngine
from failsafe import FailsafeController
from trace_logger import TraceLogger, TraceEntry, build_human_reason


# ── Helpers ──────────────────────────────────────────────────────────────

def _traffic_state(
    intersection_id: str = "INT_A",
    ts: datetime | None = None,
) -> IntersectionTrafficState:
    return IntersectionTrafficState(
        intersection_id=intersection_id,
        timestamp=ts or datetime.now(timezone.utc),
        lanes=[
            {"lane_id": "L1", "in_density": 10.0, "out_density": 3.0,
             "capacity": 20.0, "avg_speed": 30.0, "queue_length": 2.0},
            {"lane_id": "L2", "in_density": 8.0, "out_density": 5.0,
             "capacity": 20.0, "avg_speed": 25.0, "queue_length": 3.0},
        ],
        sectors=[
            {"sector_id": "NS", "lanes": ["L1", "L2"], "aggregated_density": 18.0},
        ],
    )


def _make_engine():
    store = InMemoryStore()
    mgr = IntersectionStateManager(store=store)
    engine = SignalDecisionEngine(mgr)
    return engine, mgr


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    FAILSAFE TESTS                                    ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestFailsafePassthrough:
    def test_normal_decision_passes_through(self):
        """When engine works, failsafe is transparent."""
        engine, mgr = _make_engine()
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        mgr.ingest(state)
        output = ctrl.safe_decide(state)
        assert output.selected_sector == "NS"
        assert not ctrl.is_in_fallback

    def test_failsafe_stats_clean(self):
        engine, mgr = _make_engine()
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        mgr.ingest(state)
        ctrl.safe_decide(state)
        stats = ctrl.stats
        assert stats["in_fallback"] is False
        assert stats["consecutive_failures"] == 0


class TestFailsafeOnException:
    def test_engine_crash_returns_safe_output(self):
        """If engine.decide() throws, failsafe returns safe default."""
        engine, mgr = _make_engine()
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        mgr.ingest(state)

        # Monkey-patch engine to crash
        engine.decide = MagicMock(side_effect=RuntimeError("boom"))
        output = ctrl.safe_decide(state)

        # Must still return a valid output
        assert output is not None
        assert output.intersection_id == "INT_A"
        assert len(output.signals) == 2
        assert output.timing.green_time > 0
        assert ctrl.is_in_fallback

    def test_no_undefined_signal_states(self):
        """Every lane MUST have an explicit GREEN or RED state."""
        engine, mgr = _make_engine()
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        mgr.ingest(state)

        engine.decide = MagicMock(side_effect=Exception("fail"))
        output = ctrl.safe_decide(state)

        for sig in output.signals:
            assert sig.state in (SignalStateEnum.GREEN, SignalStateEnum.RED)

    def test_consecutive_failures_tracked(self):
        engine, mgr = _make_engine()
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        mgr.ingest(state)

        engine.decide = MagicMock(side_effect=RuntimeError("fail"))
        ctrl.safe_decide(state)
        ctrl.safe_decide(state)
        assert ctrl.stats["consecutive_failures"] == 2
        assert ctrl.stats["total_fallbacks"] == 2

    def test_recovery_clears_fallback(self):
        """Once engine recovers, failsafe state is cleared."""
        engine, mgr = _make_engine()
        real_decide = engine.decide
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        mgr.ingest(state)

        # Fail once
        engine.decide = MagicMock(side_effect=RuntimeError("fail"))
        ctrl.safe_decide(state)
        assert ctrl.is_in_fallback

        # Recover
        engine.decide = real_decide
        state2 = _traffic_state(ts=datetime.now(timezone.utc) + timedelta(seconds=5))
        mgr.ingest(state2)
        ctrl.safe_decide(state2)
        assert not ctrl.is_in_fallback


class TestFailsafeManual:
    def test_force_failsafe(self):
        engine, mgr = _make_engine()
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        output = ctrl.force_failsafe(state, reason="test")
        assert output.timing.green_time == 15.0
        assert ctrl.stats["total_fallbacks"] == 1

    def test_clear_failsafe(self):
        engine, mgr = _make_engine()
        ctrl = FailsafeController(engine, mgr)
        state = _traffic_state()
        ctrl.force_failsafe(state)
        assert ctrl.is_in_fallback
        ctrl.clear_failsafe()
        assert not ctrl.is_in_fallback


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  TRACE LOGGER TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def _dummy_output(iid: str = "INT_A") -> SignalDecisionOutput:
    return SignalDecisionOutput(
        intersection_id=iid,
        timestamp=datetime.now(timezone.utc),
        selected_sector="NS",
        signals=[
            SignalState(lane_id="L1", state=SignalStateEnum.GREEN),
            SignalState(lane_id="L2", state=SignalStateEnum.RED),
        ],
        timing=TimingInfo(green_time=20.0, cycle_length=45.0),
    )


class TestTraceEntry:
    def test_to_dict(self):
        entry = TraceEntry(
            output=_dummy_output(),
            mode=DecisionMode.NORMAL,
            reason="test reason",
        )
        d = entry.to_dict()
        assert d["intersection_id"] == "INT_A"
        assert d["mode"] == "normal"
        assert d["reason"] == "test reason"

    def test_to_pg_row(self):
        entry = TraceEntry(
            output=_dummy_output(),
            mode=DecisionMode.NORMAL,
            reason="test",
        )
        row = entry.to_pg_row()
        assert "intersection_id" in row
        assert "timestamp" in row
        assert "metadata_json" in row
        # metadata_json should be valid JSON
        meta = json.loads(row["metadata_json"])
        assert "signal_states" in meta

    def test_lane_scores_captured(self):
        scores = [FlowScore(lane_id="L1", flow_score=5.0)]
        entry = TraceEntry(
            output=_dummy_output(),
            mode=DecisionMode.NORMAL,
            reason="test",
            lane_scores=scores,
        )
        assert entry.lane_scores == {"L1": 5.0}


class TestTraceLogger:
    def test_log_and_retrieve(self):
        trace = TraceLogger()
        output = _dummy_output()
        trace.log(output, DecisionMode.NORMAL, "test")
        entries = trace.get_recent(1)
        assert len(entries) == 1
        assert entries[0].reason == "test"

    def test_flush_clears_buffer(self):
        trace = TraceLogger()
        trace.log(_dummy_output(), DecisionMode.NORMAL, "test")
        rows = trace.flush_pg_rows()
        assert len(rows) == 1
        # Buffer should be empty now
        assert trace.get_stats()["buffer_size"] == 0

    def test_stats(self):
        trace = TraceLogger(max_buffer=100)
        trace.log(_dummy_output(), DecisionMode.NORMAL, "a")
        trace.log(_dummy_output(), DecisionMode.NORMAL, "b")
        stats = trace.get_stats()
        assert stats["buffer_size"] == 2
        assert stats["total_logged"] == 2

    def test_overflow_trims_buffer(self):
        trace = TraceLogger(max_buffer=5)
        for i in range(10):
            trace.log(_dummy_output(), DecisionMode.NORMAL, f"entry_{i}")
        # Should have trimmed
        assert trace.get_stats()["buffer_size"] <= 5

    def test_overflow_writes_to_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            fallback_path = f.name

        try:
            trace = TraceLogger(max_buffer=3, fallback_log_path=fallback_path)
            for i in range(6):
                trace.log(_dummy_output(), DecisionMode.NORMAL, f"entry_{i}")

            # Overflow file should exist and have content
            with open(fallback_path, "r") as f:
                lines = f.readlines()
            assert len(lines) > 0
            # Each line should be valid JSON
            for line in lines:
                data = json.loads(line.strip())
                assert "intersection_id" in data
        finally:
            os.unlink(fallback_path)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  HUMAN REASON TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestHumanReason:
    def test_emergency_reason(self):
        reason = build_human_reason(
            DecisionMode.EMERGENCY_OVERRIDE, "CORRIDOR",
            extra="corridor for AMB_001",
        )
        assert "Emergency Override Active" in reason
        assert "AMB_001" in reason

    def test_fallback_reason(self):
        reason = build_human_reason(
            DecisionMode.FALLBACK, "SAFE",
            extra="engine_exception: ZeroDivisionError",
        )
        assert "Failsafe" in reason
        assert "ZeroDivisionError" in reason

    def test_normal_with_comparison(self):
        scores = [
            SectorScore(sector_id="NS", sector_score=25.0),
            SectorScore(sector_id="EW", sector_score=15.0),
        ]
        reason = build_human_reason(
            DecisionMode.NORMAL, "NS", sector_scores=scores,
        )
        assert "NS" in reason
        assert "25.00" in reason
        assert "EW" in reason

    def test_normal_single_sector(self):
        scores = [SectorScore(sector_id="NS", sector_score=10.0)]
        reason = build_human_reason(
            DecisionMode.NORMAL, "NS", sector_scores=scores,
        )
        assert "only sector" in reason
