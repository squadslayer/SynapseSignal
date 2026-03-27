"""
Tests for the State Management Engine.

Verifies:
  • State stores current + previous correctly
  • Out-of-order timestamps are rejected
  • Skipped frames are detected and counted
  • Staleness detection works
  • Minimum dwell time enforcement
  • Multiple intersections tracked independently
"""

import time
import pytest
from datetime import datetime, timezone, timedelta

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import IntersectionTrafficState
from state_manager import IntersectionStateManager, InMemoryStore
from config import settings


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_state(
    intersection_id: str = "INT_01",
    ts: datetime | None = None,
    in_density: float = 10.0,
) -> IntersectionTrafficState:
    """Create a minimal valid IntersectionTrafficState."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    return IntersectionTrafficState(
        intersection_id=intersection_id,
        timestamp=ts,
        lanes=[
            {
                "lane_id": "L1",
                "in_density": in_density,
                "out_density": 5.0,
                "capacity": 20.0,
                "avg_speed": 30.0,
                "queue_length": 3.0,
            },
            {
                "lane_id": "L2",
                "in_density": 8.0,
                "out_density": 4.0,
                "capacity": 20.0,
                "avg_speed": 25.0,
                "queue_length": 2.0,
            },
        ],
        sectors=[
            {
                "sector_id": "NORTH_SOUTH",
                "lanes": ["L1", "L2"],
                "aggregated_density": 18.0,
            }
        ],
        emergency_state={"active": False},
    )


def _make_manager() -> IntersectionStateManager:
    """Create a manager with an in-memory store."""
    return IntersectionStateManager(store=InMemoryStore())


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                 STATE STORAGE TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestStateStorage:
    def test_first_ingest_accepted(self):
        mgr = _make_manager()
        state = _make_state()
        result = mgr.ingest(state)
        assert result.accepted is True
        assert result.frame_count == 1

    def test_current_state_stored(self):
        mgr = _make_manager()
        state = _make_state()
        mgr.ingest(state)
        current = mgr.get_current_state("INT_01")
        assert current is not None
        assert current.intersection_id == "INT_01"

    def test_previous_state_on_second_ingest(self):
        mgr = _make_manager()
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=1)

        s1 = _make_state(ts=t1, in_density=10.0)
        s2 = _make_state(ts=t2, in_density=15.0)

        mgr.ingest(s1)
        mgr.ingest(s2)

        current = mgr.get_current_state("INT_01")
        previous = mgr.get_previous_state("INT_01")

        assert current is not None
        assert previous is not None
        assert current.lanes[0].in_density == 15.0
        assert previous.lanes[0].in_density == 10.0

    def test_multiple_intersections_independent(self):
        mgr = _make_manager()
        s1 = _make_state(intersection_id="INT_01")
        s2 = _make_state(intersection_id="INT_02")

        mgr.ingest(s1)
        mgr.ingest(s2)

        assert mgr.get_current_state("INT_01") is not None
        assert mgr.get_current_state("INT_02") is not None
        assert len(mgr.get_all_intersection_ids()) == 2


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              TEMPORAL VALIDATION TESTS                               ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestTemporalValidation:
    def test_out_of_order_rejected(self):
        mgr = _make_manager()
        t1 = datetime.now(timezone.utc)
        t2 = t1 - timedelta(seconds=1)  # earlier than t1

        s1 = _make_state(ts=t1)
        s2 = _make_state(ts=t2)

        mgr.ingest(s1)
        result = mgr.ingest(s2)

        assert result.accepted is False
        assert result.reason == "out_of_order_timestamp"

    def test_duplicate_timestamp_rejected(self):
        mgr = _make_manager()
        t1 = datetime.now(timezone.utc)

        s1 = _make_state(ts=t1)
        s2 = _make_state(ts=t1)  # same timestamp

        mgr.ingest(s1)
        result = mgr.ingest(s2)

        assert result.accepted is False

    def test_sequential_timestamps_accepted(self):
        mgr = _make_manager()
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=1)
        t3 = t2 + timedelta(seconds=1)

        r1 = mgr.ingest(_make_state(ts=t1))
        r2 = mgr.ingest(_make_state(ts=t2))
        r3 = mgr.ingest(_make_state(ts=t3))

        assert r1.accepted and r2.accepted and r3.accepted
        assert r3.frame_count == 3


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              SKIPPED FRAME DETECTION TESTS                           ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestSkippedFrames:
    def test_large_gap_detected(self):
        mgr = _make_manager()
        t1 = datetime.now(timezone.utc)
        # Create a gap larger than MAX_FRAME_GAP_SEC
        t2 = t1 + timedelta(seconds=settings.MAX_FRAME_GAP_SEC + 1)

        mgr.ingest(_make_state(ts=t1))
        result = mgr.ingest(_make_state(ts=t2))

        assert result.accepted is True
        assert result.skipped_frames == 1

    def test_normal_gap_no_skip(self):
        mgr = _make_manager()
        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=0.5)

        mgr.ingest(_make_state(ts=t1))
        result = mgr.ingest(_make_state(ts=t2))

        assert result.accepted is True
        assert result.skipped_frames == 0

    def test_multiple_skips_counted(self):
        mgr = _make_manager()
        gap = settings.MAX_FRAME_GAP_SEC + 1
        t = datetime.now(timezone.utc)

        mgr.ingest(_make_state(ts=t))
        t += timedelta(seconds=gap)
        mgr.ingest(_make_state(ts=t))  # skip 1
        t += timedelta(seconds=gap)
        result = mgr.ingest(_make_state(ts=t))  # skip 2

        assert result.skipped_frames == 2


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              STALENESS DETECTION TESTS                               ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestStaleness:
    def test_unknown_intersection_is_stale(self):
        mgr = _make_manager()
        assert mgr.is_stale("NONEXISTENT") is True

    def test_fresh_state_not_stale(self):
        mgr = _make_manager()
        mgr.ingest(_make_state())
        assert mgr.is_stale("INT_01") is False


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              DWELL TIME ENFORCEMENT TESTS                            ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestDwellTime:
    def test_no_sector_allows_switch(self):
        mgr = _make_manager()
        mgr.ingest(_make_state())
        # No active sector → should allow any switch
        assert mgr.can_switch_sector("INT_01", "EAST_WEST") is True

    def test_same_sector_always_allowed(self):
        mgr = _make_manager()
        mgr.ingest(_make_state())
        mgr.set_active_sector("INT_01", "NORTH_SOUTH")
        assert mgr.can_switch_sector("INT_01", "NORTH_SOUTH") is True

    def test_switch_blocked_during_dwell(self):
        mgr = _make_manager()
        mgr.ingest(_make_state())
        mgr.set_active_sector("INT_01", "NORTH_SOUTH")
        # Immediately try to switch — should be blocked
        assert mgr.can_switch_sector("INT_01", "EAST_WEST") is False

    def test_switch_allowed_after_dwell(self):
        mgr = _make_manager()
        mgr.ingest(_make_state())
        mgr.set_active_sector("INT_01", "NORTH_SOUTH")
        # Wait past the dwell time
        time.sleep(settings.MIN_DWELL_TIME_SEC + 0.1)
        assert mgr.can_switch_sector("INT_01", "EAST_WEST") is True


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              STATE STORE SYNC TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestStoreSync:
    def test_state_synced_to_store(self):
        store = InMemoryStore()
        mgr = IntersectionStateManager(store=store)

        state = _make_state()
        mgr.ingest(state)

        live = store.get_live_state("INT_01")
        assert live is not None
        assert live["intersection_id"] == "INT_01"

    def test_store_updated_on_each_ingest(self):
        store = InMemoryStore()
        mgr = IntersectionStateManager(store=store)

        t1 = datetime.now(timezone.utc)
        t2 = t1 + timedelta(seconds=1)

        mgr.ingest(_make_state(ts=t1, in_density=10.0))
        mgr.ingest(_make_state(ts=t2, in_density=20.0))

        live = store.get_live_state("INT_01")
        assert live["lanes"][0]["in_density"] == 20.0


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              DIAGNOSTIC STATS TESTS                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TestDiagnostics:
    def test_stats_returns_frame_count(self):
        mgr = _make_manager()
        t = datetime.now(timezone.utc)
        mgr.ingest(_make_state(ts=t))
        mgr.ingest(_make_state(ts=t + timedelta(seconds=1)))

        stats = mgr.get_record_stats("INT_01")
        assert stats is not None
        assert stats["frame_count"] == 2

    def test_stats_none_for_unknown(self):
        mgr = _make_manager()
        assert mgr.get_record_stats("UNKNOWN") is None
