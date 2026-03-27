"""
Tests for the Flow Score Computation Engine.

Verifies:
  • Flow score formula correctness
  • Safe division (capacity edge cases)
  • out_density clamping
  • Normalization
  • Sector aggregation and ranking
"""

import pytest
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import LaneState, SectorState, IntersectionTrafficState, FlowScore
from flow_engine import (
    compute_lane_flow_score,
    compute_all_lane_flow_scores,
    normalize_flow_scores,
    compute_sector_scores,
    select_best_sector,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _lane(
    lane_id: str = "L1",
    in_d: float = 10.0,
    out_d: float = 5.0,
    cap: float = 20.0,
) -> LaneState:
    return LaneState(
        lane_id=lane_id, in_density=in_d, out_density=out_d,
        capacity=cap, avg_speed=30.0, queue_length=3.0,
    )


def _state(lanes: list[LaneState], sectors: list[SectorState]):
    return IntersectionTrafficState(
        intersection_id="INT_01",
        timestamp=datetime.now(timezone.utc),
        lanes=lanes,
        sectors=sectors,
        emergency_state={"active": False},
    )


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   LANE FLOW SCORE TESTS                              ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestLaneFlowScore:
    def test_basic_formula(self):
        """flow_score = 10 * (1 - 5/20) = 10 * 0.75 = 7.5"""
        lane = _lane(in_d=10, out_d=5, cap=20)
        result = compute_lane_flow_score(lane)
        assert result.flow_score == 7.5

    def test_zero_in_density(self):
        """No demand → score = 0."""
        lane = _lane(in_d=0, out_d=5, cap=20)
        result = compute_lane_flow_score(lane)
        assert result.flow_score == 0.0

    def test_zero_out_density(self):
        """Empty exit → score = in_density (maximum flow)."""
        lane = _lane(in_d=10, out_d=0, cap=20)
        result = compute_lane_flow_score(lane)
        assert result.flow_score == 10.0

    def test_exit_at_capacity(self):
        """Exit fully blocked → score = 0."""
        lane = _lane(in_d=10, out_d=20, cap=20)
        result = compute_lane_flow_score(lane)
        assert result.flow_score == 0.0

    def test_out_density_exceeds_capacity_clamped(self):
        """out_density > capacity is clamped by schema → score = 0."""
        lane = _lane(in_d=10, out_d=25, cap=20)
        # Pydantic clamps out_density to capacity (20)
        result = compute_lane_flow_score(lane)
        assert result.flow_score == 0.0

    def test_high_density_high_score(self):
        """High demand + clear exit → high score."""
        lane = _lane(in_d=50, out_d=5, cap=100)
        result = compute_lane_flow_score(lane)
        # 50 * (1 - 5/100) = 50 * 0.95 = 47.5
        assert result.flow_score == 47.5

    def test_score_always_non_negative(self):
        """Score should never be negative."""
        for in_d in [0, 1, 10, 50]:
            for out_d in [0, 5, 20, 25]:
                lane = _lane(in_d=in_d, out_d=out_d, cap=20)
                score = compute_lane_flow_score(lane).flow_score
                assert score >= 0.0, f"Negative score: in={in_d}, out={out_d}"

    def test_preserves_lane_id(self):
        lane = _lane(lane_id="LANE_X")
        result = compute_lane_flow_score(lane)
        assert result.lane_id == "LANE_X"


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   NORMALIZATION TESTS                                ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestNormalization:
    def test_normalizes_to_0_1(self):
        scores = [
            FlowScore(lane_id="A", flow_score=10),
            FlowScore(lane_id="B", flow_score=20),
            FlowScore(lane_id="C", flow_score=30),
        ]
        normed = normalize_flow_scores(scores)
        values = [s.flow_score for s in normed]
        assert min(values) == 0.0
        assert max(values) == 1.0

    def test_single_score_returns_zero(self):
        scores = [FlowScore(lane_id="A", flow_score=5)]
        normed = normalize_flow_scores(scores)
        assert normed[0].flow_score == 0.0

    def test_all_equal_returns_zeros(self):
        scores = [
            FlowScore(lane_id="A", flow_score=5),
            FlowScore(lane_id="B", flow_score=5),
        ]
        normed = normalize_flow_scores(scores)
        assert all(s.flow_score == 0.0 for s in normed)

    def test_empty_list(self):
        assert normalize_flow_scores([]) == []


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  SECTOR AGGREGATION TESTS                            ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestSectorScores:
    def test_single_sector(self):
        sectors = [SectorState(sector_id="NS", lanes=["L1", "L2"], aggregated_density=0)]
        lane_scores = [
            FlowScore(lane_id="L1", flow_score=7.5),
            FlowScore(lane_id="L2", flow_score=5.0),
        ]
        results = compute_sector_scores(sectors, lane_scores)
        assert len(results) == 1
        assert results[0].sector_score == 12.5

    def test_two_sectors_ranked(self):
        sectors = [
            SectorState(sector_id="NS", lanes=["L1"], aggregated_density=0),
            SectorState(sector_id="EW", lanes=["L2"], aggregated_density=0),
        ]
        lane_scores = [
            FlowScore(lane_id="L1", flow_score=3.0),
            FlowScore(lane_id="L2", flow_score=8.0),
        ]
        results = compute_sector_scores(sectors, lane_scores)
        # EW should rank first (higher score)
        assert results[0].sector_id == "EW"
        assert results[0].sector_score == 8.0
        assert results[1].sector_id == "NS"

    def test_missing_lane_defaults_to_zero(self):
        sectors = [SectorState(sector_id="NS", lanes=["L1", "L_MISSING"], aggregated_density=0)]
        lane_scores = [FlowScore(lane_id="L1", flow_score=5.0)]
        results = compute_sector_scores(sectors, lane_scores)
        assert results[0].sector_score == 5.0

    def test_select_best_sector(self):
        sectors = [
            SectorState(sector_id="NS", lanes=["L1"], aggregated_density=0),
            SectorState(sector_id="EW", lanes=["L2"], aggregated_density=0),
        ]
        lane_scores = [
            FlowScore(lane_id="L1", flow_score=3.0),
            FlowScore(lane_id="L2", flow_score=8.0),
        ]
        results = compute_sector_scores(sectors, lane_scores)
        best = select_best_sector(results)
        assert best is not None
        assert best.sector_id == "EW"

    def test_select_best_empty(self):
        assert select_best_sector([]) is None

    def test_three_sectors_correct_order(self):
        sectors = [
            SectorState(sector_id="NS", lanes=["L1"], aggregated_density=0),
            SectorState(sector_id="EW", lanes=["L2"], aggregated_density=0),
            SectorState(sector_id="NE", lanes=["L3"], aggregated_density=0),
        ]
        lane_scores = [
            FlowScore(lane_id="L1", flow_score=5.0),
            FlowScore(lane_id="L2", flow_score=2.0),
            FlowScore(lane_id="L3", flow_score=9.0),
        ]
        results = compute_sector_scores(sectors, lane_scores)
        assert results[0].sector_id == "NE"
        assert results[1].sector_id == "NS"
        assert results[2].sector_id == "EW"


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  FULL PIPELINE TESTS                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestFullPipeline:
    def test_end_to_end_flow_to_sector(self):
        """Run the full flow: lanes → flow scores → sector scores."""
        l1 = _lane("L1", in_d=20, out_d=5, cap=40)   # score = 20*(1-5/40) = 17.5
        l2 = _lane("L2", in_d=10, out_d=8, cap=20)   # score = 10*(1-8/20) = 6.0
        l3 = _lane("L3", in_d=15, out_d=2, cap=30)   # score = 15*(1-2/30) = 14.0
        l4 = _lane("L4", in_d=5, out_d=10, cap=20)   # score = 5*(1-10/20) = 2.5

        sectors = [
            SectorState(sector_id="NS", lanes=["L1", "L2"], aggregated_density=0),
            SectorState(sector_id="EW", lanes=["L3", "L4"], aggregated_density=0),
        ]
        state = _state([l1, l2, l3, l4], sectors)

        lane_scores = compute_all_lane_flow_scores(state)
        sector_scores = compute_sector_scores(sectors, lane_scores)
        best = select_best_sector(sector_scores)

        # NS: 17.5 + 6.0 = 23.5
        # EW: 14.0 + 2.5 = 16.5
        assert best is not None
        assert best.sector_id == "NS"
        assert best.sector_score == 23.5
