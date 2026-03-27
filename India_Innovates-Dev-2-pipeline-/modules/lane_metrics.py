"""
Phase 4 — Lane-Level Feature Extraction
Computes per-lane traffic metrics: in_density, avg_speed, queue_length.
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class LaneMetrics:
    """Traffic metrics for a single lane."""
    lane_id: str
    in_density: int         # number of vehicles in this lane
    avg_speed: float        # average velocity of vehicles (pixels/sec)
    queue_length: int       # count of vehicles with speed near zero
    vehicle_ids: List[int]  # track IDs of vehicles in this lane

    def to_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "in_density": self.in_density,
            "avg_speed": round(self.avg_speed, 2),
            "queue_length": self.queue_length,
            "vehicle_ids": self.vehicle_ids,
        }


class LaneMetricsComputer:
    """
    Computes per-lane traffic metrics from lane-mapped tracked objects.
    
    Metrics:
    - in_density: count of vehicles currently in the lane
    - avg_speed: mean velocity across all vehicles in lane
    - queue_length: number of vehicles with speed ≈ 0 (stopped/very slow)
    """

    def __init__(self, stopped_speed_threshold: float = 5.0):
        """
        Args:
            stopped_speed_threshold: max velocity (px/sec) to consider a 
                                     vehicle as "stopped" / queued
        """
        self.stopped_threshold = stopped_speed_threshold

    def compute(self, lane_assignments: Dict[str, list]) -> Dict[str, LaneMetrics]:
        """
        Compute metrics for all lanes.
        
        Args:
            lane_assignments: dict of lane_id -> list of tracked objects
                              (objects must have .velocity and .track_id or .object_id)
        
        Returns:
            Dict of lane_id -> LaneMetrics
        """
        results = {}

        for lane_id, objects in lane_assignments.items():
            n_vehicles = len(objects)

            # Extract velocities and IDs
            velocities = []
            vehicle_ids = []
            queued = 0

            for obj in objects:
                vel = getattr(obj, "velocity", 0.0)
                obj_id = getattr(obj, "track_id", getattr(obj, "object_id", 0))

                velocities.append(vel)
                vehicle_ids.append(obj_id)

                if vel <= self.stopped_threshold:
                    queued += 1

            avg_speed = sum(velocities) / len(velocities) if velocities else 0.0

            results[lane_id] = LaneMetrics(
                lane_id=lane_id,
                in_density=n_vehicles,
                avg_speed=avg_speed,
                queue_length=queued,
                vehicle_ids=vehicle_ids,
            )

        return results

    def compute_for_detections(self, lane_assignments: Dict[str, list]) -> Dict[str, LaneMetrics]:
        """
        Compute metrics when objects are DetectedObject instances (not Tracks).
        Uses object_id and velocity attributes.
        """
        return self.compute(lane_assignments)
