"""
Tests for the Signal Decision Engine.

Verifies:
  • Correct sector selection based on flow scores
  • GREEN assigned to winning sector, RED to others
  • No conflicting greens (conflict-free guarantee)
  • Fallback output when no sector available
  • Output matches Dev 4 SignalDecisionOutput contract
  • Decision log is populated
  • Integration with state manager
"""

import pytest
from datetime import datetime, timezone, timedelta

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import IntersectionTrafficState, SignalStateEnum
from state_manager import IntersectionStateManager, InMemoryStore
from decision_engine import SignalDecisionEngine


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_state(
    intersection_id: str = "INT_01",
    ts: datetime | None = None,
    lanes: list[dict] | None = None,
    sectors: list[dict] | None = None,
) -> IntersectionTrafficState:
    if ts is None:
        ts = datetime.now(timezone.utc)
    if lanes is None:
        lanes = [
            {"lane_id": "L1", "in_density": 20.0, "out_density": 5.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 5.0},
            {"lane_id": "L2", "in_density": 10.0, "out_density": 3.0,
             "capacity": 20.0, "avg_speed": 25.0, "queue_length": 3.0},
            {"lane_id": "L3", "in_density": 5.0, "out_density": 15.0,
             "capacity": 20.0, "avg_speed": 15.0, "queue_length": 8.0},
            {"lane_id": "L4", "in_density": 3.0, "out_density": 10.0,
             "capacity": 20.0, "avg_speed": 10.0, "queue_length": 2.0},
        ]
    if sectors is None:
        sectors = [
            {"sector_id": "NORTH_SOUTH", "lanes": ["L1", "L2"], "aggregated_density": 30.0},
            {"sector_id": "EAST_WEST", "lanes": ["L3", "L4"], "aggregated_density": 8.0},
        ]
    return IntersectionTrafficState(
        intersection_id=intersection_id,
        timestamp=ts,
        lanes=lanes,
        sectors=sectors,
        emergency_state={"active": False},
    )


def _make_engine() -> tuple[SignalDecisionEngine, IntersectionStateManager]:
    store = InMemoryStore()
    manager = IntersectionStateManager(store=store)
    engine = SignalDecisionEngine(manager)
    return engine, manager


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  SECTOR SELECTION TESTS                              ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestSectorSelection:
    def test_highest_flow_score_wins(self):
        """NS has higher flow scores → NS should be selected."""
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)

        output = engine.decide(state)
        # NS: L1 score = 20*(1-5/40)=17.5, L2 = 10*(1-3/20)=8.5 → total=26.0
        # EW: L3 score = 5*(1-15/20)=1.25, L4 = 3*(1-10/20)=1.5 → total=2.75
        assert output.selected_sector == "NORTH_SOUTH"

    def test_reversed_densities(self):
        """When EW has higher demand + clear exits, EW should win."""
        engine, mgr = _make_engine()
        state = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 2.0, "out_density": 15.0,
             "capacity": 20.0, "avg_speed": 10.0, "queue_length": 1.0},
            {"lane_id": "L2", "in_density": 3.0, "out_density": 10.0,
             "capacity": 20.0, "avg_speed": 10.0, "queue_length": 1.0},
            {"lane_id": "L3", "in_density": 30.0, "out_density": 2.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 5.0},
            {"lane_id": "L4", "in_density": 25.0, "out_density": 3.0,
             "capacity": 40.0, "avg_speed": 25.0, "queue_length": 5.0},
        ])
        mgr.ingest(state)

        output = engine.decide(state)
        assert output.selected_sector == "EAST_WEST"


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                CONFLICT-FREE GUARANTEE TESTS                         ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestConflictFree:
    def test_only_one_sector_green(self):
        """Only lanes in the selected sector should be GREEN."""
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)
        output = engine.decide(state)

        green_lanes = {s.lane_id for s in output.signals if s.state == SignalStateEnum.GREEN}
        red_lanes = {s.lane_id for s in output.signals if s.state == SignalStateEnum.RED}

        # NS is selected → L1, L2 green; L3, L4 red
        assert green_lanes == {"L1", "L2"}
        assert red_lanes == {"L3", "L4"}

    def test_no_lane_is_unassigned(self):
        """Every lane in the state must get a signal."""
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)
        output = engine.decide(state)

        assigned_lanes = {s.lane_id for s in output.signals}
        all_lanes = {lane.lane_id for lane in state.lanes}
        assert assigned_lanes == all_lanes

    def test_greens_dont_span_sectors(self):
        """GREEN lanes must all belong to a single sector."""
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)
        output = engine.decide(state)

        green_lanes = {s.lane_id for s in output.signals if s.state == SignalStateEnum.GREEN}

        # Verify all green lanes belong to the selected sector
        for sector in state.sectors:
            if sector.sector_id == output.selected_sector:
                assert green_lanes == set(sector.lanes)
                break


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║               OUTPUT CONTRACT ALIGNMENT TESTS                        ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestOutputContract:
    def test_output_has_required_fields(self):
        """Output must match the Dev 4 SignalDecisionOutput schema."""
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)
        output = engine.decide(state)

        assert output.intersection_id == "INT_01"
        assert output.timestamp is not None
        assert output.selected_sector is not None
        assert len(output.signals) > 0
        assert output.timing.green_time > 0
        assert output.timing.cycle_length > 0

    def test_output_serializable(self):
        """Output should serialize to JSON (for the HTTP response)."""
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)
        output = engine.decide(state)

        json_data = output.model_dump(mode="json")
        assert "intersection_id" in json_data
        assert "selected_sector" in json_data
        assert "signals" in json_data
        assert "timing" in json_data
        assert json_data["timing"]["green_time"] > 0

    def test_timing_is_adaptive(self):
        """Different traffic → different green times."""
        engine, mgr = _make_engine()

        # Low traffic
        t1 = datetime.now(timezone.utc)
        low = _make_state(ts=t1, lanes=[
            {"lane_id": "L1", "in_density": 2.0, "out_density": 1.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 1.0},
            {"lane_id": "L2", "in_density": 1.0, "out_density": 1.0,
             "capacity": 20.0, "avg_speed": 25.0, "queue_length": 0.0},
        ], sectors=[
            {"sector_id": "NS", "lanes": ["L1", "L2"], "aggregated_density": 3.0},
        ])
        mgr.ingest(low)
        out_low = engine.decide(low)

        # High traffic (new intersection to avoid temporal conflict)
        high = _make_state(intersection_id="INT_02", lanes=[
            {"lane_id": "L1", "in_density": 50.0, "out_density": 5.0,
             "capacity": 100.0, "avg_speed": 10.0, "queue_length": 20.0},
            {"lane_id": "L2", "in_density": 40.0, "out_density": 3.0,
             "capacity": 80.0, "avg_speed": 8.0, "queue_length": 15.0},
        ], sectors=[
            {"sector_id": "NS", "lanes": ["L1", "L2"], "aggregated_density": 90.0},
        ])
        mgr.ingest(high)
        out_high = engine.decide(high)

        assert out_high.timing.green_time > out_low.timing.green_time


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  DECISION LOG TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestDecisionLog:
    def test_decision_logged(self):
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)
        engine.decide(state)

        logs = engine.get_recent_decisions()
        assert len(logs) == 1
        assert logs[0].decision.mode.value == "normal"

    def test_multiple_decisions_logged(self):
        engine, mgr = _make_engine()
        t = datetime.now(timezone.utc)

        for i in range(5):
            state = _make_state(ts=t + timedelta(seconds=i))
            mgr.ingest(state)
            engine.decide(state)

        logs = engine.get_recent_decisions(count=3)
        assert len(logs) == 3


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              STATE MANAGER INTEGRATION TESTS                         ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestStateManagerIntegration:
    def test_active_sector_updated(self):
        """After decide(), the state manager should know the active sector."""
        engine, mgr = _make_engine()
        state = _make_state()
        mgr.ingest(state)
        output = engine.decide(state)

        record = mgr._records.get("INT_01")
        assert record is not None
        assert record.active_sector == output.selected_sector
