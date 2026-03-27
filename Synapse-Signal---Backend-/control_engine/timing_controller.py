"""
SynapseSignal Control Engine — Adaptive Timing Controller
==========================================================
Phase 8: Dynamically compute green phase duration.

The timing controller answers: "How LONG should the selected sector
stay green?"

Inputs:
  • Aggregated density of the selected sector
  • Queue length of lanes in the sector
  • Configurable bounds (min/max green time)

Design principles:
  1. Higher density → longer green (more vehicles to clear).
  2. Longer queues → extended green (queue clearance bonus).
  3. Starvation prevention: maximum green caps even high-demand sectors.
  4. Minimum green: every sector gets at least MIN_GREEN_SEC.
  5. Cycle length scales with the number of sectors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from schemas import IntersectionTrafficState, SectorScore, TimingInfo

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                     TIMING PARAMETERS                                ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@dataclass(frozen=True)
class TimingParams:
    """
    Tunable parameters for the adaptive timing controller.

    Attributes:
        min_green_sec:       Absolute minimum green duration.
        max_green_sec:       Absolute maximum green (starvation cap).
        base_green_sec:      Baseline green when density is moderate.
        density_weight:      How much each unit of density adds to green.
        queue_weight:        Bonus seconds per unit of queue length.
        inter_phase_sec:     Yellow/all-red clearance between phases.
    """
    min_green_sec: float = 8.0
    max_green_sec: float = 60.0
    base_green_sec: float = 15.0
    density_weight: float = 0.5
    queue_weight: float = 0.8
    inter_phase_sec: float = 3.0


# Default parameters — can be overridden per deployment.
DEFAULT_TIMING = TimingParams()


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    GREEN TIME COMPUTATION                            ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def compute_green_time(
    sector_score: SectorScore,
    state: IntersectionTrafficState,
    params: TimingParams = DEFAULT_TIMING,
) -> float:
    """
    Compute the optimal green duration for the selected sector.

    Algorithm:
        green = base
              + density_weight × aggregated_density
              + queue_weight   × total_queue_length
        green = clamp(green, min_green, max_green)

    The density and queue values come from the lanes belonging to
    the selected sector.

    Args:
        sector_score: The winning sector (with lane membership).
        state:        Full intersection state (needed for queue lengths).
        params:       Tunable timing parameters.

    Returns:
        Green duration in seconds, clamped to [min, max].
    """
    # Gather lane data for the sector's member lanes.
    sector_lane_ids = {fs.lane_id for fs in sector_score.lanes}
    sector_lanes = [
        lane for lane in state.lanes if lane.lane_id in sector_lane_ids
    ]

    # Aggregated density: sum of in_density across sector lanes.
    total_density = sum(lane.in_density for lane in sector_lanes)

    # Total queue: sum of queue_length across sector lanes.
    total_queue = sum(lane.queue_length for lane in sector_lanes)

    # Compute raw green time.
    green = (
        params.base_green_sec
        + params.density_weight * total_density
        + params.queue_weight * total_queue
    )

    # Clamp to [min, max] — prevents starvation of other sectors.
    green = max(params.min_green_sec, min(green, params.max_green_sec))

    logger.debug(
        "Green time for sector %s: %.1fs "
        "(density=%.1f, queue=%.1f, base=%.1f)",
        sector_score.sector_id, green,
        total_density, total_queue, params.base_green_sec,
    )
    return round(green, 1)


def compute_cycle_length(
    green_time: float,
    num_sectors: int,
    params: TimingParams = DEFAULT_TIMING,
) -> float:
    """
    Estimate the full cycle length for the intersection.

    Formula:
        cycle = green_time
              + (num_sectors − 1) × estimated_other_green
              + num_sectors × inter_phase_sec

    The "other green" is estimated as the base green for simplicity.
    In practice, each sector would get its own computed green, but
    the cycle length is used for display and coordination, not exact
    timing.

    Args:
        green_time:     Duration of the current green phase.
        num_sectors:    Total number of sectors at the intersection.
        params:         Timing parameters.

    Returns:
        Estimated cycle length in seconds.
    """
    if num_sectors <= 1:
        return green_time + params.inter_phase_sec

    other_phases = (num_sectors - 1) * params.base_green_sec
    clearance = num_sectors * params.inter_phase_sec
    cycle = green_time + other_phases + clearance
    return round(cycle, 1)


def build_timing_info(
    sector_score: SectorScore,
    state: IntersectionTrafficState,
    params: TimingParams = DEFAULT_TIMING,
) -> TimingInfo:
    """
    Build a complete TimingInfo for the Dev 4 output contract.

    Convenience function that computes green time + cycle length
    and wraps them in the output schema.
    """
    green = compute_green_time(sector_score, state, params)
    cycle = compute_cycle_length(green, len(state.sectors), params)
    return TimingInfo(green_time=green, cycle_length=cycle)
