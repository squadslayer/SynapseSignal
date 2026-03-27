"""
Phase 6 — Flow Readiness Feature Computation
Prepares flow features (in_density, out_density, capacity) per lane
as direct inputs for Dev 3's flow_score computation.
"""

from typing import Dict
from dataclasses import dataclass


@dataclass
class FlowFeatures:
    """Flow-readiness features for a single lane — direct inputs for Dev 3."""
    lane_id: str
    in_density: int
    out_density: int
    capacity: int
    avg_speed: float
    queue_length: int

    def to_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "in_density": self.in_density,
            "out_density": self.out_density,
            "capacity": self.capacity,
            "avg_speed": round(self.avg_speed, 2),
            "queue_length": self.queue_length,
        }


class FlowFeatureComputer:
    """
    Combines lane metrics (Phase 4) + downstream state (Phase 5)
    into unified flow-ready features for each lane.
    
    Dev 3 will use these to compute:
        flow_score = in_density * (1 - out_density / capacity)
    """

    def compute(
        self,
        lane_metrics: Dict[str, "LaneMetrics"],
        downstream_states: Dict[str, "DownstreamState"],
    ) -> Dict[str, FlowFeatures]:
        """
        Compute flow features for all incoming lanes.
        
        Args:
            lane_metrics: from Phase 4
            downstream_states: from Phase 5
        
        Returns:
            Dict of lane_id -> FlowFeatures (only for incoming lanes)
        """
        results = {}

        for lane_id, ds_state in downstream_states.items():
            metrics = lane_metrics.get(lane_id)

            if metrics is None:
                continue

            results[lane_id] = FlowFeatures(
                lane_id=lane_id,
                in_density=metrics.in_density,
                out_density=ds_state.out_density,
                capacity=ds_state.capacity,
                avg_speed=metrics.avg_speed,
                queue_length=metrics.queue_length,
            )

        return results
