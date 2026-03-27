"""
Tests for Pydantic schema validation.

Verifies:
  • Valid inputs are accepted
  • capacity=0 is rejected
  • Negative densities are clamped
  • Empty lanes/sectors are rejected
  • out_density > capacity is clamped
  • Emergency state requires vehicle_type when active
  • Sector-lane coverage is enforced
"""

import pytest
from datetime import datetime, timezone

from schemas import (
    LaneState,
    SectorState,
    EmergencyState,
    IntersectionTrafficState,
    EmergencyVehicleType,
    GeoPosition,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_lane(
    lane_id: str = "L1",
    in_density: float = 10.0,
    out_density: float = 5.0,
    capacity: float = 20.0,
) -> dict:
    return {
        "lane_id": lane_id,
        "in_density": in_density,
        "out_density": out_density,
        "capacity": capacity,
        "avg_speed": 30.0,
        "queue_length": 3.0,
    }


def _make_sector(sector_id: str = "NORTH_SOUTH", lanes: list[str] | None = None) -> dict:
    return {
        "sector_id": sector_id,
        "lanes": ["L1"] if lanes is None else lanes,
        "aggregated_density": 10.0,
    }


def _make_valid_payload(**overrides) -> dict:
    base = {
        "intersection_id": "INT_01",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lanes": [_make_lane("L1"), _make_lane("L2")],
        "sectors": [_make_sector("NORTH_SOUTH", ["L1", "L2"])],
        "emergency_state": {"active": False},
    }
    base.update(overrides)
    return base


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    LANE STATE TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestLaneState:
    def test_valid_lane(self):
        lane = LaneState(**_make_lane())
        assert lane.in_density == 10.0
        assert lane.capacity == 20.0

    def test_capacity_zero_rejected(self):
        with pytest.raises(Exception):
            LaneState(**_make_lane(capacity=0))

    def test_capacity_negative_rejected(self):
        with pytest.raises(Exception):
            LaneState(**_make_lane(capacity=-5))

    def test_negative_in_density_rejected(self):
        with pytest.raises(Exception):
            LaneState(**_make_lane(in_density=-1))

    def test_negative_out_density_rejected(self):
        with pytest.raises(Exception):
            LaneState(**_make_lane(out_density=-1))

    def test_out_density_clamped_to_capacity(self):
        """out_density > capacity should be clamped to capacity."""
        lane = LaneState(**_make_lane(out_density=25.0, capacity=20.0))
        assert lane.out_density == 20.0  # clamped

    def test_out_density_equal_to_capacity(self):
        """out_density == capacity is valid (flow_score = 0)."""
        lane = LaneState(**_make_lane(out_density=20.0, capacity=20.0))
        assert lane.out_density == 20.0

    def test_empty_lane_id_rejected(self):
        with pytest.raises(Exception):
            LaneState(**_make_lane(lane_id=""))


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   SECTOR STATE TESTS                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestSectorState:
    def test_valid_sector(self):
        sector = SectorState(**_make_sector())
        assert sector.sector_id == "NORTH_SOUTH"

    def test_empty_lanes_rejected(self):
        with pytest.raises(Exception):
            SectorState(**_make_sector(lanes=[]))


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                 EMERGENCY STATE TESTS                                ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestEmergencyState:
    def test_inactive_valid(self):
        e = EmergencyState(active=False)
        assert e.active is False

    def test_active_requires_vehicle_type(self):
        with pytest.raises(Exception):
            EmergencyState(active=True)

    def test_active_with_vehicle_type_valid(self):
        e = EmergencyState(
            active=True,
            vehicle_type=EmergencyVehicleType.AMBULANCE,
            vehicle_id="EMR_01",
        )
        assert e.vehicle_type == EmergencyVehicleType.AMBULANCE

    def test_invalid_vehicle_type_rejected(self):
        with pytest.raises(Exception):
            EmergencyState(active=True, vehicle_type="helicopter")


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║           INTERSECTION TRAFFIC STATE TESTS                           ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestIntersectionTrafficState:
    def test_valid_payload(self):
        state = IntersectionTrafficState(**_make_valid_payload())
        assert state.intersection_id == "INT_01"
        assert len(state.lanes) == 2

    def test_empty_lanes_rejected(self):
        with pytest.raises(Exception):
            IntersectionTrafficState(**_make_valid_payload(lanes=[]))

    def test_empty_sectors_rejected(self):
        with pytest.raises(Exception):
            IntersectionTrafficState(**_make_valid_payload(sectors=[]))

    def test_uncovered_lanes_rejected(self):
        """Lanes not covered by any sector should fail validation."""
        payload = _make_valid_payload(
            lanes=[_make_lane("L1"), _make_lane("L2"), _make_lane("L3")],
            sectors=[_make_sector("NORTH_SOUTH", ["L1", "L2"])],
            # L3 is not covered by any sector
        )
        with pytest.raises(Exception, match="not covered"):
            IntersectionTrafficState(**payload)

    def test_missing_intersection_id_rejected(self):
        payload = _make_valid_payload()
        del payload["intersection_id"]
        with pytest.raises(Exception):
            IntersectionTrafficState(**payload)

    def test_missing_timestamp_rejected(self):
        payload = _make_valid_payload()
        del payload["timestamp"]
        with pytest.raises(Exception):
            IntersectionTrafficState(**payload)

    def test_default_emergency_state(self):
        """If emergency_state is omitted, it defaults to inactive."""
        payload = _make_valid_payload()
        del payload["emergency_state"]
        state = IntersectionTrafficState(**payload)
        assert state.emergency_state.active is False


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   GEO POSITION TESTS                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestGeoPosition:
    def test_valid_coords(self):
        pos = GeoPosition(lat=28.6139, lon=77.2090)
        assert pos.lat == 28.6139

    def test_lat_out_of_range(self):
        with pytest.raises(Exception):
            GeoPosition(lat=91.0, lon=0)

    def test_lon_out_of_range(self):
        with pytest.raises(Exception):
            GeoPosition(lat=0, lon=181.0)
