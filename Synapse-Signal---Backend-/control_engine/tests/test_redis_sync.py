"""
Tests for Redis sync layer.

Uses fakeredis to avoid requiring a real Redis instance.
Verifies:
  • Intersection state is written to correct key
  • Signal state is written to correct key
  • Corridor state is written correctly
  • Graceful handling when Redis is unavailable
  • get_live_state retrieves what was synced
"""

import json
import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from schemas import IntersectionTrafficState
from redis_client import RedisSync


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_state() -> IntersectionTrafficState:
    return IntersectionTrafficState(
        intersection_id="INT_01",
        timestamp=datetime.now(timezone.utc),
        lanes=[
            {
                "lane_id": "L1",
                "in_density": 10.0,
                "out_density": 5.0,
                "capacity": 20.0,
                "avg_speed": 30.0,
                "queue_length": 3.0,
            },
        ],
        sectors=[
            {
                "sector_id": "NORTH_SOUTH",
                "lanes": ["L1"],
                "aggregated_density": 10.0,
            }
        ],
        emergency_state={"active": False},
    )


def _make_connected_sync():
    """Create a RedisSync with a fakeredis backend."""
    try:
        import fakeredis
        sync = RedisSync()
        sync._client = fakeredis.FakeRedis(decode_responses=True)
        return sync
    except ImportError:
        pytest.skip("fakeredis not installed")


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              INTERSECTION STATE SYNC TESTS                           ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestIntersectionSync:
    def test_sync_writes_correct_key(self):
        sync = _make_connected_sync()
        state = _make_state()

        sync.sync_intersection_state("INT_01", state)

        raw = sync._client.get("intersection:INT_01")
        assert raw is not None
        data = json.loads(raw)
        assert data["intersection_id"] == "INT_01"
        assert len(data["lanes"]) == 1

    def test_get_live_state_returns_synced(self):
        sync = _make_connected_sync()
        state = _make_state()

        sync.sync_intersection_state("INT_01", state)
        live = sync.get_live_state("INT_01")

        assert live is not None
        assert live["intersection_id"] == "INT_01"

    def test_get_live_state_unknown_returns_none(self):
        sync = _make_connected_sync()
        assert sync.get_live_state("UNKNOWN") is None


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              SIGNAL STATE SYNC TESTS                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestSignalSync:
    def test_sync_signal_writes_key(self):
        sync = _make_connected_sync()
        sync.sync_signal_state(
            "INT_01", "NORTH_SOUTH", "GREEN",
            datetime.now(timezone.utc).isoformat(),
        )

        raw = sync._client.get("signal:INT_01")
        assert raw is not None
        data = json.loads(raw)
        assert data["sector"] == "NORTH_SOUTH"
        assert data["state"] == "GREEN"

    def test_get_signal_state(self):
        sync = _make_connected_sync()
        sync.sync_signal_state(
            "INT_02", "EAST_WEST", "RED",
            datetime.now(timezone.utc).isoformat(),
        )

        result = sync.get_signal_state("INT_02")
        assert result is not None
        assert result["state"] == "RED"


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              CORRIDOR SYNC TESTS                                     ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestCorridorSync:
    def test_sync_corridor_writes_key(self):
        sync = _make_connected_sync()
        sync.sync_corridor_state({
            "route": ["INT_01", "INT_02", "INT_03"],
            "current_position": "INT_01",
            "next_intersection": "INT_02",
        })

        raw = sync._client.get("corridor:active")
        assert raw is not None
        data = json.loads(raw)
        assert data["route"] == ["INT_01", "INT_02", "INT_03"]


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              GRACEFUL DISCONNECTION TESTS                            ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestGracefulDegradation:
    def test_sync_with_no_client(self):
        """Sync should silently skip when Redis is not connected."""
        sync = RedisSync()
        sync._client = None  # explicitly disconnected

        # These should NOT raise
        sync.sync_intersection_state("INT_01", _make_state())
        sync.sync_signal_state("INT_01", "NS", "GREEN", "now")
        sync.sync_corridor_state({"route": []})

        assert sync.get_live_state("INT_01") is None
        assert sync.get_signal_state("INT_01") is None

    def test_is_connected_false_when_no_client(self):
        sync = RedisSync()
        sync._client = None
        assert sync.is_connected is False
