"""
Phase 3 — Lane-Level Mapping
Assigns each tracked vehicle to a lane using point-in-polygon testing
on the vehicle's centroid against configured lane ROI polygons.
"""

from typing import List, Dict, Tuple, Optional


def point_in_polygon(point: Tuple[int, int], polygon: List[List[int]]) -> bool:
    """
    Ray-casting algorithm to check if a point is inside a polygon.
    
    Args:
        point: (x, y) coordinate
        polygon: list of [x, y] vertices (convex or concave)
    
    Returns:
        True if point is inside the polygon
    """
    x, y = point
    n = len(polygon)
    inside = False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


class LaneMapper:
    """
    Maps tracked vehicles to lanes using ROI polygon containment.
    
    Each lane is defined by a polygon in pixel coordinates.
    A vehicle's centroid is tested against each lane polygon.
    """

    def __init__(self, lane_configs: List[dict]):
        """
        Args:
            lane_configs: list of lane dicts from intersection_config.json,
                          each with 'lane_id' and 'roi_polygon'
        """
        self.lanes = {}
        for lane in lane_configs:
            self.lanes[lane["lane_id"]] = {
                "roi_polygon": lane["roi_polygon"],
                "direction": lane.get("direction", ""),
                "sector_id": lane.get("sector_id", ""),
                "downstream_lane": lane.get("downstream_lane"),
                "capacity": lane.get("capacity", 10),
            }

    def assign_lane(self, centroid: Tuple[int, int]) -> Optional[str]:
        """
        Determine which lane a vehicle centroid belongs to.
        
        Returns:
            lane_id string, or None if not in any lane
        """
        for lane_id, lane_info in self.lanes.items():
            if point_in_polygon(centroid, lane_info["roi_polygon"]):
                return lane_id
        return None

    def map_frame(self, tracked_objects: list) -> Dict[str, list]:
        """
        Assign all tracked objects in a frame to their lanes.
        
        Args:
            tracked_objects: list of DetectedObject or Track instances
                             (must have .centroid and .object_id / .track_id)
        
        Returns:
            Dict mapping lane_id -> list of object references
        """
        lane_assignments = {lane_id: [] for lane_id in self.lanes}

        for obj in tracked_objects:
            centroid = obj.centroid
            lane_id = self.assign_lane(centroid)

            if lane_id is not None:
                # Set lane on the object if it has lane_id attribute
                if hasattr(obj, "lane_id"):
                    obj.lane_id = lane_id
                lane_assignments[lane_id].append(obj)

        return lane_assignments

    def get_lane_ids(self) -> List[str]:
        """Get all configured lane IDs."""
        return list(self.lanes.keys())

    def get_incoming_lanes(self) -> List[str]:
        """Get lane IDs that are incoming (have downstream mappings)."""
        return [
            lid for lid, info in self.lanes.items()
            if info.get("downstream_lane") is not None
        ]

    def get_downstream_lane(self, lane_id: str) -> Optional[str]:
        """Get the downstream lane for a given incoming lane."""
        lane_info = self.lanes.get(lane_id)
        if lane_info:
            return lane_info.get("downstream_lane")
        return None
