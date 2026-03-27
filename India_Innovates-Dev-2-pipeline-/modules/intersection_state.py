"""
Phase 8 — Intersection Traffic State Modeling
Combines all lane metrics, flow features, sector data, and emergency state
into a single unified intersection state for Dev 3.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class EmergencyVehicleState:
    """State of an emergency vehicle at this intersection."""
    track_id: int
    vehicle_type: str        # "ambulance", "police", "fire_truck"
    lane_id: Optional[str]
    centroid: tuple
    velocity: float

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "vehicle_type": self.vehicle_type,
            "lane_id": self.lane_id,
            "centroid": list(self.centroid),
            "velocity": round(self.velocity, 2),
        }


@dataclass
class EmergencyState:
    """Emergency state at an intersection."""
    active: bool
    count: int
    vehicles: List[EmergencyVehicleState] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "count": self.count,
            "vehicles": [v.to_dict() for v in self.vehicles],
        }


@dataclass
class IntersectionState:
    """Complete traffic state for a single intersection — the core Dev 2 output."""
    intersection_id: str
    timestamp: float
    lanes: list              # list of FlowFeatures dicts
    sectors: list            # list of SectorState dicts
    emergency_state: dict    # EmergencyState dict

    def to_dict(self) -> dict:
        return {
            "intersection_id": self.intersection_id,
            "timestamp": self.timestamp,
            "lanes": self.lanes,
            "sectors": self.sectors,
            "emergency_state": self.emergency_state,
        }


class IntersectionStateBuilder:
    """
    Combines all pipeline outputs into a single intersection state.
    
    Inputs needed:
    - Flow features (Phase 6) — lane-level data
    - Sector states (Phase 7) — grouped data
    - Emergency info — from tracker + lane mapper
    """

    def __init__(self, intersection_id: str):
        self.intersection_id = intersection_id

    def build(
        self,
        timestamp: float,
        flow_features: Dict[str, "FlowFeatures"],
        sector_states: Dict[str, "SectorState"],
        lane_metrics: Dict[str, "LaneMetrics"],
        active_tracks: list,
        lane_assignments: Dict[str, list],
    ) -> IntersectionState:
        """
        Build the complete intersection state.
        
        Args:
            timestamp: current frame timestamp
            flow_features: Phase 6 output (incoming lanes only)
            sector_states: Phase 7 output
            lane_metrics: Phase 4 output (all lanes)
            active_tracks: list of Track objects from Phase 2
            lane_assignments: Phase 3 output
        """
        # Build lane data — include ALL lanes with metrics
        lanes_data = []
        for lane_id, metrics in lane_metrics.items():
            lane_dict = metrics.to_dict()
            # Add flow features if available (incoming lanes)
            if lane_id in flow_features:
                ff = flow_features[lane_id]
                lane_dict["out_density"] = ff.out_density
                lane_dict["capacity"] = ff.capacity
            else:
                lane_dict["out_density"] = 0
                lane_dict["capacity"] = 0
            lanes_data.append(lane_dict)

        # Build sector data
        sectors_data = [s.to_dict() for s in sector_states.values()]

        # Build emergency state
        emergency_vehicles = []
        for track in active_tracks:
            if track.is_emergency:
                ev = EmergencyVehicleState(
                    track_id=track.track_id,
                    vehicle_type=track.subtype,
                    lane_id=self._find_track_lane(track, lane_assignments),
                    centroid=track.centroid,
                    velocity=track.velocity,
                )
                emergency_vehicles.append(ev)

        emergency_state = EmergencyState(
            active=len(emergency_vehicles) > 0,
            count=len(emergency_vehicles),
            vehicles=emergency_vehicles,
        )

        return IntersectionState(
            intersection_id=self.intersection_id,
            timestamp=timestamp,
            lanes=lanes_data,
            sectors=sectors_data,
            emergency_state=emergency_state.to_dict(),
        )

    def _find_track_lane(self, track, lane_assignments: Dict[str, list]) -> Optional[str]:
        """Find which lane a track is currently in."""
        for lane_id, objects in lane_assignments.items():
            for obj in objects:
                tid = getattr(obj, "track_id", getattr(obj, "object_id", None))
                if tid == track.track_id:
                    return lane_id
        return None
