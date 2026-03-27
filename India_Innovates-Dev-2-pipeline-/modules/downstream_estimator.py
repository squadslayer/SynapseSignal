"""
Phase 5 — Downstream State Estimation
Models the outgoing lane conditions: out_density and capacity.
Determines how congested the downstream path is.
"""

from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class DownstreamState:
    """State of a downstream (outgoing) lane."""
    lane_id: str
    downstream_lane_id: str
    out_density: int       # vehicles in the downstream lane
    capacity: int          # max vehicles the downstream lane can hold

    def to_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "downstream_lane_id": self.downstream_lane_id,
            "out_density": self.out_density,
            "capacity": self.capacity,
        }


class DownstreamEstimator:
    """
    Estimates downstream lane conditions for flow-aware control.
    
    For each incoming lane:
    - Looks up its downstream (outgoing) lane
    - Gets the current density of that downstream lane
    - Returns out_density and capacity
    
    If downstream data is unavailable, uses a heuristic estimate.
    """

    def __init__(self, lane_configs: list):
        """
        Args:
            lane_configs: list of lane config dicts with 
                          'lane_id', 'downstream_lane', 'capacity'
        """
        self.downstream_map = {}   # incoming_lane -> downstream_lane
        self.capacity_map = {}     # lane_id -> capacity

        for lane in lane_configs:
            lid = lane["lane_id"]
            self.capacity_map[lid] = lane.get("capacity", 10)

            downstream = lane.get("downstream_lane")
            if downstream:
                self.downstream_map[lid] = downstream

    def estimate(self, lane_metrics: Dict[str, "LaneMetrics"]) -> Dict[str, DownstreamState]:
        """
        Estimate downstream state for all incoming lanes.
        
        Args:
            lane_metrics: dict of lane_id -> LaneMetrics (from Phase 4)
        
        Returns:
            Dict of incoming_lane_id -> DownstreamState
        """
        results = {}

        for incoming_lane, downstream_lane in self.downstream_map.items():
            # Get downstream lane metrics if available
            if downstream_lane in lane_metrics:
                out_density = lane_metrics[downstream_lane].in_density
            else:
                # Heuristic: assume 30% occupancy if no data
                capacity = self.capacity_map.get(downstream_lane, 10)
                out_density = int(capacity * 0.3)

            capacity = self.capacity_map.get(downstream_lane, 10)

            results[incoming_lane] = DownstreamState(
                lane_id=incoming_lane,
                downstream_lane_id=downstream_lane,
                out_density=out_density,
                capacity=max(capacity, 1),  # prevent division by zero
            )

        return results
