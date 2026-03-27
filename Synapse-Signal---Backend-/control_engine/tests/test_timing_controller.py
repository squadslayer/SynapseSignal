"""
Tests for the Adaptive Timing Controller.

Verifies:
  • Green time scales with density and queue length
  • Minimum green enforced (starvation prevention)
  • Maximum green cap enforced
  • Cycle length calculation
  • Custom parameters are respected
"""

import pytest
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import LaneState, SectorState, IntersectionTrafficState, FlowScore, SectorScore
from timing_controller import (
    compute_green_time,
    compute_cycle_length,
    build_timing_info,
    TimingParams,
    DEFAULT_TIMING,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_state(
    lanes: list[dict] | None = None,
    sectors: list[dict] | None = None,
) -> IntersectionTrafficState:
    if lanes is None:
        lanes = [
            {"lane_id": "L1", "in_density": 20.0, "out_density": 5.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 5.0},
            {"lane_id": "L2", "in_density": 10.0, "out_density": 3.0,
             "capacity": 20.0, "avg_speed": 25.0, "queue_length": 3.0},
        ]
    if sectors is None:
        sectors = [
            {"sector_id": "NS", "lanes": ["L1", "L2"], "aggregated_density": 30.0},
        ]
    return IntersectionTrafficState(
        intersection_id="INT_01",
        timestamp=datetime.now(timezone.utc),
        lanes=lanes,
        sectors=sectors,
        emergency_state={"active": False},
    )


def _sector_score(sector_id: str = "NS", lane_ids: list[str] | None = None):
    ids = lane_ids or ["L1", "L2"]
    return SectorScore(
        sector_id=sector_id,
        sector_score=10.0,
        lanes=[FlowScore(lane_id=lid, flow_score=5.0) for lid in ids],
    )


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   GREEN TIME TESTS                                   ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestGreenTime:
    def test_base_case(self):
        """Green time should be reasonable for moderate traffic."""
        state = _make_state()
        ss = _sector_score()
        green = compute_green_time(ss, state)
        assert green >= DEFAULT_TIMING.min_green_sec
        assert green <= DEFAULT_TIMING.max_green_sec

    def test_higher_density_longer_green(self):
        """More vehicles waiting → longer green."""
        low = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 5.0, "out_density": 2.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 1.0},
        ], sectors=[{"sector_id": "NS", "lanes": ["L1"], "aggregated_density": 5.0}])
        high = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 50.0, "out_density": 2.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 1.0},
        ], sectors=[{"sector_id": "NS", "lanes": ["L1"], "aggregated_density": 50.0}])

        ss = _sector_score("NS", ["L1"])
        green_low = compute_green_time(ss, low)
        green_high = compute_green_time(ss, high)
        assert green_high > green_low

    def test_higher_queue_longer_green(self):
        """Longer queues → longer green (queue clearance bonus)."""
        short_q = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 10.0, "out_density": 2.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 1.0},
        ], sectors=[{"sector_id": "NS", "lanes": ["L1"], "aggregated_density": 10.0}])
        long_q = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 10.0, "out_density": 2.0,
             "capacity": 40.0, "avg_speed": 30.0, "queue_length": 20.0},
        ], sectors=[{"sector_id": "NS", "lanes": ["L1"], "aggregated_density": 10.0}])

        ss = _sector_score("NS", ["L1"])
        green_short = compute_green_time(ss, short_q)
        green_long = compute_green_time(ss, long_q)
        assert green_long > green_short

    def test_min_green_enforced(self):
        """Even with zero traffic, min green is enforced."""
        state = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 0.0, "out_density": 0.0,
             "capacity": 40.0, "avg_speed": 0.0, "queue_length": 0.0},
        ], sectors=[{"sector_id": "NS", "lanes": ["L1"], "aggregated_density": 0.0}])

        params = TimingParams(min_green_sec=10.0, base_green_sec=5.0)
        ss = _sector_score("NS", ["L1"])
        green = compute_green_time(ss, state, params)
        assert green == 10.0  # min_green overrides low base

    def test_max_green_enforced(self):
        """Even with extreme traffic, max green is capped."""
        state = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 200.0, "out_density": 0.0,
             "capacity": 40.0, "avg_speed": 0.0, "queue_length": 100.0},
        ], sectors=[{"sector_id": "NS", "lanes": ["L1"], "aggregated_density": 200.0}])

        ss = _sector_score("NS", ["L1"])
        green = compute_green_time(ss, state)
        assert green == DEFAULT_TIMING.max_green_sec

    def test_custom_params(self):
        """Custom timing parameters are respected."""
        params = TimingParams(
            min_green_sec=5, max_green_sec=30,
            base_green_sec=10, density_weight=1.0, queue_weight=0.0,
        )
        state = _make_state(lanes=[
            {"lane_id": "L1", "in_density": 10.0, "out_density": 0.0,
             "capacity": 40.0, "avg_speed": 0.0, "queue_length": 50.0},
        ], sectors=[{"sector_id": "NS", "lanes": ["L1"], "aggregated_density": 10.0}])

        ss = _sector_score("NS", ["L1"])
        green = compute_green_time(ss, state, params)
        # base(10) + density_weight(1.0)*10 = 20, queue_weight=0 so no queue bonus
        assert green == 20.0


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  CYCLE LENGTH TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestCycleLength:
    def test_single_sector(self):
        """Single sector: just green + clearance."""
        cycle = compute_cycle_length(20.0, 1)
        assert cycle == 20.0 + DEFAULT_TIMING.inter_phase_sec

    def test_two_sectors(self):
        """Two sectors: green + other_base + 2*clearance."""
        cycle = compute_cycle_length(20.0, 2)
        expected = 20.0 + DEFAULT_TIMING.base_green_sec + 2 * DEFAULT_TIMING.inter_phase_sec
        assert cycle == expected

    def test_three_sectors(self):
        cycle = compute_cycle_length(20.0, 3)
        expected = 20.0 + 2 * DEFAULT_TIMING.base_green_sec + 3 * DEFAULT_TIMING.inter_phase_sec
        assert cycle == expected


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  BUILD TIMING INFO TESTS                             ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestBuildTimingInfo:
    def test_returns_timing_info(self):
        state = _make_state()
        ss = _sector_score()
        timing = build_timing_info(ss, state)
        assert timing.green_time > 0
        assert timing.cycle_length > timing.green_time
