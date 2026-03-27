"""
SynapseSignal Control Engine — Flow Score Computation
=====================================================
Phase 3: Compute flow feasibility per lane.
Phase 4: Aggregate lane scores into sector scores.

The core formula:
    flow_score = in_density × (1 − out_density / capacity)

This rewards lanes with:
  • High incoming demand (many vehicles waiting)
  • Low downstream blockage (exit is clear)

It penalises:
  • Sending vehicles into already congested exits
  • Lanes where downstream is at or over capacity

Design:
  • Safe division: capacity=0 → flow_score=0 (captured by schema,
    but defended here too).
  • Clamping: out_density/capacity ratio capped at 1.0.
  • Normalization: optional min-max normalization across all lanes
    for cross-intersection comparability.
"""

from __future__ import annotations

import logging
from typing import Optional

from schemas import (
    IntersectionTrafficState,
    LaneState,
    SectorState,
    FlowScore,
    SectorScore,
)

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    LANE-LEVEL FLOW SCORES                            ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def compute_lane_flow_score(lane: LaneState) -> FlowScore:
    """
    Compute the flow feasibility score for a single lane.

    Formula:
        flow_score = in_density × (1 − out_density / capacity)

    Edge cases:
        • capacity ≤ 0  → score = 0  (should never happen after validation)
        • out_density ≥ capacity → score = 0  (exit is fully blocked)
        • in_density = 0 → score = 0  (no demand)

    Returns:
        FlowScore with the lane_id and computed score.
    """
    if lane.capacity <= 0:
        logger.warning(
            "Lane %s has capacity=%.2f (≤0); defaulting flow_score=0",
            lane.lane_id, lane.capacity,
        )
        return FlowScore(lane_id=lane.lane_id, flow_score=0.0)

    # Clamp the ratio to [0, 1] to guarantee non-negative scores.
    ratio = min(lane.out_density / lane.capacity, 1.0)
    score = lane.in_density * (1.0 - ratio)

    # Score is naturally ≥ 0 because in_density ≥ 0 and (1-ratio) ∈ [0,1].
    return FlowScore(lane_id=lane.lane_id, flow_score=round(score, 6))


def compute_all_lane_flow_scores(
    state: IntersectionTrafficState,
) -> list[FlowScore]:
    """Compute flow scores for every lane in the intersection state."""
    scores = [compute_lane_flow_score(lane) for lane in state.lanes]
    logger.debug(
        "Lane flow scores for %s: %s",
        state.intersection_id,
        {s.lane_id: s.flow_score for s in scores},
    )
    return scores


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                        NORMALIZATION                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def normalize_flow_scores(scores: list[FlowScore]) -> list[FlowScore]:
    """
    Min-max normalize flow scores to [0, 1] range.

    Useful when comparing scores across intersections with very
    different density/capacity magnitudes.

    If all scores are equal (or only one lane), returns 0.0 for all
    (since there is no relative priority).
    """
    if not scores:
        return scores

    values = [s.flow_score for s in scores]
    min_v = min(values)
    max_v = max(values)
    spread = max_v - min_v

    if spread == 0:
        return [
            FlowScore(lane_id=s.lane_id, flow_score=0.0) for s in scores
        ]

    return [
        FlowScore(
            lane_id=s.lane_id,
            flow_score=round((s.flow_score - min_v) / spread, 6),
        )
        for s in scores
    ]


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   SECTOR-LEVEL AGGREGATION                           ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def compute_sector_scores(
    sectors: list[SectorState],
    lane_scores: list[FlowScore],
) -> list[SectorScore]:
    """
    Aggregate lane-level flow scores into sector scores.

    Formula:
        sector_score = Σ flow_score(lane)  for lane in sector

    Each sector gets the sum of its constituent lane scores.
    The sector with the highest score represents the direction
    where traffic can flow most effectively.

    Args:
        sectors:      Sector definitions with lane membership lists.
        lane_scores:  Pre-computed per-lane flow scores.

    Returns:
        Ranked list of SectorScores (highest first).
    """
    # Build a lookup: lane_id → FlowScore
    score_map: dict[str, FlowScore] = {s.lane_id: s for s in lane_scores}

    results: list[SectorScore] = []
    for sector in sectors:
        member_scores: list[FlowScore] = []
        total = 0.0

        for lane_id in sector.lanes:
            fs = score_map.get(lane_id)
            if fs is not None:
                member_scores.append(fs)
                total += fs.flow_score
            else:
                logger.warning(
                    "Lane %s in sector %s has no flow score — "
                    "defaulting to 0",
                    lane_id, sector.sector_id,
                )
                member_scores.append(
                    FlowScore(lane_id=lane_id, flow_score=0.0)
                )

        results.append(
            SectorScore(
                sector_id=sector.sector_id,
                sector_score=round(total, 6),
                lanes=member_scores,
            )
        )

    # Sort descending by score (best sector first).
    results.sort(key=lambda s: s.sector_score, reverse=True)

    logger.debug(
        "Sector scores: %s",
        {s.sector_id: s.sector_score for s in results},
    )
    return results


def select_best_sector(
    sector_scores: list[SectorScore],
) -> Optional[SectorScore]:
    """
    Return the sector with the highest aggregated flow score.

    Returns None only if sector_scores is empty.
    Ties are broken by the first sector in the (already-sorted) list.
    """
    if not sector_scores:
        return None
    return sector_scores[0]
