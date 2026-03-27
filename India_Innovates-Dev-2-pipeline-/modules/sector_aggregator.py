"""
Phase 7 — Sector-Wise Aggregation
Groups lanes into sectors (NORTH_SOUTH, EAST_WEST) and aggregates metrics.
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class SectorState:
    """Aggregated traffic state for a sector (group of lanes)."""
    sector_id: str
    lane_ids: List[str]
    aggregated_density: int     # total vehicles across all lanes in sector
    avg_speed: float            # average speed across sector
    total_queue: int            # total queued vehicles across sector

    def to_dict(self) -> dict:
        return {
            "sector_id": self.sector_id,
            "lanes": self.lane_ids,
            "aggregated_density": self.aggregated_density,
            "avg_speed": round(self.avg_speed, 2),
            "total_queue": self.total_queue,
        }


class SectorAggregator:
    """
    Groups lanes into sectors and aggregates traffic metrics.
    
    Sectors typically represent movement groups:
    - NORTH_SOUTH: lanes for north-south traffic flow
    - EAST_WEST: lanes for east-west traffic flow
    """

    def __init__(self, sector_configs: List[dict]):
        """
        Args:
            sector_configs: list of sector dicts from config, each with:
                            'sector_id' and 'lanes' (list of lane_ids)
        """
        self.sectors = {}
        for sector in sector_configs:
            self.sectors[sector["sector_id"]] = sector["lanes"]

    def aggregate(self, lane_metrics: Dict[str, "LaneMetrics"]) -> Dict[str, SectorState]:
        """
        Aggregate lane metrics into sector-level state.
        
        Args:
            lane_metrics: dict of lane_id -> LaneMetrics from Phase 4
        
        Returns:
            Dict of sector_id -> SectorState
        """
        results = {}

        for sector_id, lane_ids in self.sectors.items():
            total_density = 0
            total_speed = 0.0
            total_queue = 0
            n_lanes_with_data = 0

            for lane_id in lane_ids:
                metrics = lane_metrics.get(lane_id)
                if metrics:
                    total_density += metrics.in_density
                    total_speed += metrics.avg_speed
                    total_queue += metrics.queue_length
                    n_lanes_with_data += 1

            avg_speed = total_speed / n_lanes_with_data if n_lanes_with_data > 0 else 0.0

            results[sector_id] = SectorState(
                sector_id=sector_id,
                lane_ids=lane_ids,
                aggregated_density=total_density,
                avg_speed=avg_speed,
                total_queue=total_queue,
            )

        return results
