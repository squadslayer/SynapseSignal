"""
SynapseSignal Control Engine — Pydantic Schemas
================================================
Strict data-validation models aligned with the Dev 3 Interface Contract.

Input  (Dev 2 → Dev 3):  IntersectionTrafficState, RouteData
Output (Dev 3 → Dev 4):  SignalDecisionOutput, MultiIntersectionCoordination
Persist(Dev 3 → Dev 5):  SignalLogEntry, CorridorLogEntry, RouteEntry, etc.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                        ENUMERATIONS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class SignalStateEnum(str, Enum):
    GREEN = "GREEN"
    RED = "RED"
    YELLOW = "YELLOW"


class EmergencyVehicleType(str, Enum):
    AMBULANCE = "ambulance"
    POLICE = "police"
    FIRE = "fire"


class CorridorStatus(str, Enum):
    ACTIVE = "active"
    REPLANNED = "replanned"
    COMPLETED = "completed"


class DecisionMode(str, Enum):
    NORMAL = "normal"
    EMERGENCY_OVERRIDE = "emergency_override"
    FALLBACK = "fallback"


class DecisionReason(str, Enum):
    FLOW_SCORE = "flow_score"
    EMERGENCY_OVERRIDE = "emergency_override"
    CITY_STRATEGY = "city_strategy"
    FALLBACK = "fallback"


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   INPUT MODELS  (Dev 2 → Dev 3)                      ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class GeoPosition(BaseModel):
    """Geographic coordinates in WGS-84."""
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lon: float = Field(..., ge=-180, le=180, description="Longitude")


class LaneState(BaseModel):
    """Per-lane traffic metrics from Dev 2."""
    lane_id: str = Field(..., min_length=1)
    in_density: float = Field(..., ge=0, description="Vehicles waiting to move (≥ 0)")
    out_density: float = Field(..., ge=0, description="Downstream occupancy (≥ 0)")
    capacity: float = Field(..., gt=0, description="Max downstream capacity (must be > 0)")
    avg_speed: float = Field(0.0, ge=0, description="Average speed of vehicles in lane")
    queue_length: float = Field(0.0, ge=0, description="Estimated queue length")

    @field_validator("out_density")
    @classmethod
    def clamp_out_density_ratio(cls, v: float, info) -> float:
        """Ensure out_density does not exceed capacity.
        
        If out_density > capacity, clamp it to capacity so that
        out_density/capacity ≤ 1.0 and flow_score ≥ 0.
        """
        # Note: capacity is validated before out_density in field order,
        # but we access it via info.data which may not have it yet during
        # individual field validation. The model_validator below handles
        # the cross-field check.
        return v

    @model_validator(mode="after")
    def enforce_density_capacity_ratio(self) -> "LaneState":
        """Clamp out_density to capacity to prevent negative flow scores."""
        if self.out_density > self.capacity:
            self.out_density = self.capacity
        return self


class SectorState(BaseModel):
    """Sector-level aggregation (e.g., NORTH_SOUTH, EAST_WEST)."""
    sector_id: str = Field(..., min_length=1)
    lanes: list[str] = Field(..., min_length=1, description="Lane IDs in this sector")
    aggregated_density: float = Field(0.0, ge=0)


class EmergencyState(BaseModel):
    """Emergency vehicle presence information."""
    active: bool = False
    vehicle_type: Optional[EmergencyVehicleType] = None
    vehicle_id: Optional[str] = None
    lane_id: Optional[str] = None
    position: Optional[GeoPosition] = None
    velocity: Optional[float] = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_active_fields(self) -> "EmergencyState":
        """If emergency is active, vehicle_type must be present."""
        if self.active and self.vehicle_type is None:
            raise ValueError(
                "vehicle_type is required when emergency is active"
            )
        return self


class CityIntersectionNode(BaseModel):
    """A node in the city-level traffic graph."""
    intersection_id: str = Field(..., min_length=1)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    aggregated_density: float = Field(0.0, ge=0)


class CityEdge(BaseModel):
    """An edge (road) in the city-level traffic graph."""
    edge_id: str = Field(..., min_length=1)
    from_intersection: str = Field(..., min_length=1)
    to_intersection: str = Field(..., min_length=1)
    distance: float = Field(..., gt=0)
    vehicle_count: int = Field(0, ge=0)
    avg_speed: float = Field(0.0, ge=0)
    congestion_level: str = Field("low", description="low | medium | high")


class CityState(BaseModel):
    """City-level graph state."""
    intersections: list[CityIntersectionNode] = Field(default_factory=list)
    edges: list[CityEdge] = Field(default_factory=list)


class IntersectionTrafficState(BaseModel):
    """
    Top-level input payload from Dev 2.
    
    This is the **single source of truth** that Dev 3 ingests each frame.
    Schema validation here prevents bad data from reaching the control logic.
    """
    intersection_id: str = Field(..., min_length=1)
    timestamp: datetime

    lanes: list[LaneState] = Field(..., min_length=1,
        description="Must have at least one lane")
    sectors: list[SectorState] = Field(..., min_length=1,
        description="Must have at least one sector")
    emergency_state: EmergencyState = Field(
        default_factory=EmergencyState)
    city_state: Optional[CityState] = None

    @model_validator(mode="after")
    def validate_sector_lane_coverage(self) -> "IntersectionTrafficState":
        """Verify every lane belongs to at least one sector."""
        lane_ids = {lane.lane_id for lane in self.lanes}
        sector_lane_ids: set[str] = set()
        for sector in self.sectors:
            sector_lane_ids.update(sector.lanes)

        uncovered = lane_ids - sector_lane_ids
        if uncovered:
            raise ValueError(
                f"Lanes {uncovered} are not covered by any sector. "
                "All lanes must belong to at least one sector."
            )
        return self


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  ROUTE MODELS  (Dev 2 additions → Dev 3)             ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class Route(BaseModel):
    """A candidate route between intersections."""
    route_id: str = Field(..., min_length=1)
    path: list[str] = Field(..., min_length=2,
        description="Ordered intersection IDs")
    total_distance: float = Field(..., gt=0)
    avg_congestion: float = Field(0.0, ge=0)
    estimated_time: float = Field(..., gt=0)


class RouteData(BaseModel):
    """Route intelligence from Dev 2 additions."""
    routes: list[Route] = Field(default_factory=list)
    emergency_position: Optional[GeoPosition] = None


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                 OUTPUT MODELS  (Dev 3 → Dev 4)                       ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class SignalState(BaseModel):
    """Per-lane signal command."""
    lane_id: str
    state: SignalStateEnum


class TimingInfo(BaseModel):
    """Signal timing for the current phase."""
    green_time: float = Field(..., gt=0, description="Seconds for current green")
    cycle_length: float = Field(..., gt=0, description="Total cycle in seconds")


class ETAEntry(BaseModel):
    """Predicted green window for a corridor intersection."""
    intersection_id: str
    green_start: float = Field(..., ge=0, description="Offset in seconds")
    green_duration: float = Field(..., gt=0)


class CorridorState(BaseModel):
    """Active green corridor information for Dev 4 visualization."""
    route: list[str] = Field(..., min_length=1)
    active_corridor: list[str] = Field(default_factory=list)
    current_intersection: str
    eta_sequence: list[ETAEntry] = Field(default_factory=list)
    status: CorridorStatus = CorridorStatus.ACTIVE


class SignalDecisionOutput(BaseModel):
    """
    What Dev 3 sends to Dev 4 each control cycle.
    
    This is the **official control output contract** consumed by the
    React dashboard for real-time visualization.
    """
    intersection_id: str
    timestamp: datetime
    selected_sector: str

    signals: list[SignalState]
    timing: TimingInfo

    corridor: Optional[CorridorState] = None


class TimingOffset(BaseModel):
    """Phase offset for multi-intersection coordination."""
    intersection_id: str
    offset_seconds: float


class MultiIntersectionCoordination(BaseModel):
    """City-wide coordination output for Dev 4 map overlays."""
    intersections: list[SignalDecisionOutput] = Field(default_factory=list)
    timing_offsets: list[TimingOffset] = Field(default_factory=list)
    strategy: str = "local_control"  # green_wave | local_control | emergency_override


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              PERSISTENCE MODELS  (Dev 3 → Dev 5)                     ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class SignalLogEntry(BaseModel):
    """Row inserted into PostgreSQL `signal_logs` table."""
    intersection_id: int
    timestamp: datetime
    selected_sector: str
    reason: DecisionReason


class CorridorLogEntry(BaseModel):
    """Row inserted into PostgreSQL `corridor_logs` table."""
    route_id: int
    intersection_id: int
    green_start: datetime
    green_end: datetime


class RouteEntry(BaseModel):
    """Row inserted into PostgreSQL `routes` table."""
    event_id: int
    total_distance: float
    estimated_time: float


class RouteNodeEntry(BaseModel):
    """Row inserted into PostgreSQL `route_nodes` table."""
    route_id: int
    intersection_id: int
    sequence_order: int


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                 INTERNAL MODELS  (Dev 3 only)                        ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class FlowScore(BaseModel):
    """Computed flow feasibility per lane."""
    lane_id: str
    flow_score: float


class SectorScore(BaseModel):
    """Aggregated flow score per sector."""
    sector_id: str
    sector_score: float
    lanes: list[FlowScore] = Field(default_factory=list)


class ControlDecision(BaseModel):
    """Captures the full reasoning behind a signal decision."""
    mode: DecisionMode
    selected_sector: str
    reason: str
    flow_scores: list[FlowScore] = Field(default_factory=list)
    sector_scores: list[SectorScore] = Field(default_factory=list)


class FallbackState(BaseModel):
    """Active when the system enters safe-mode."""
    fallback_active: bool = True
    reason: str
    mode: str = "default_cycle"


class DecisionLog(BaseModel):
    """Full audit log entry for a single control cycle."""
    timestamp: datetime
    input: IntersectionTrafficState
    flow_scores: list[FlowScore] = Field(default_factory=list)
    sector_scores: list[SectorScore] = Field(default_factory=list)
    decision: ControlDecision
    reason: str
