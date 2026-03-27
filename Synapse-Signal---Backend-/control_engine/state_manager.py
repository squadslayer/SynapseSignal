"""
SynapseSignal Control Engine — State Management Engine
======================================================
Maintains temporal continuity for each intersection.

Responsibilities:
  • Store current_state and previous_state per intersection
  • Reject out-of-order timestamps
  • Detect skipped frames and carry forward previous state
  • Mark state as stale if no update within threshold
  • Enforce minimum dwell time to prevent erratic sector switching
  • Thread-safe via per-intersection locks
  • Dependency-injectable via StateStore protocol for testability
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

from schemas import IntersectionTrafficState
from config import settings

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                      PROTOCOLS (DI contracts)                        ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@runtime_checkable
class StateStore(Protocol):
    """
    Abstraction for the persistence backend that receives live state.
    
    Implementations:
      • RedisSync     — production (writes to Redis)
      • InMemoryStore — testing   (dict-backed, no external deps)
    """

    def sync_intersection_state(
        self, intersection_id: str, state: IntersectionTrafficState
    ) -> None:
        """Push the latest validated state to the store."""
        ...

    def get_live_state(
        self, intersection_id: str
    ) -> Optional[dict]:
        """Retrieve the current live state (for debugging / API)."""
        ...


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  IN-MEMORY STORE  (for testing)                      ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class InMemoryStore:
    """Simple dict-backed state store used in unit tests."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def sync_intersection_state(
        self, intersection_id: str, state: IntersectionTrafficState
    ) -> None:
        self._data[intersection_id] = state.model_dump(mode="json")

    def get_live_state(self, intersection_id: str) -> Optional[dict]:
        return self._data.get(intersection_id)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                   INTERSECTION STATE RECORD                          ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@dataclass
class IntersectionRecord:
    """
    Holds the temporal state for a single intersection.
    
    Attributes:
        current_state:  The latest validated traffic state.
        previous_state: The state that was current before this update.
        last_updated:   Wall-clock time of the last successful update.
        active_sector:  Which sector currently has GREEN.
        sector_since:   When the active_sector was first selected.
        frame_count:    Total frames ingested for this intersection.
        skipped_frames: Count of detected frame gaps.
    """
    current_state: Optional[IntersectionTrafficState] = None
    previous_state: Optional[IntersectionTrafficState] = None
    last_updated: Optional[datetime] = None
    active_sector: Optional[str] = None
    sector_since: Optional[datetime] = None
    frame_count: int = 0
    skipped_frames: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  STATE MANAGEMENT ENGINE                             ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class IntersectionStateManager:
    """
    Core state machine for all intersection traffic states.
    
    Design principles:
      1. One IntersectionRecord per intersection_id.
      2. Each update is validated temporally before acceptance.
      3. The StateStore is synced on every accepted update.
      4. The manager is thread-safe per intersection.
    
    Usage:
        store = RedisSync(...)          # or InMemoryStore() for tests
        manager = IntersectionStateManager(store=store)
        result = manager.ingest(validated_traffic_state)
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._records: dict[str, IntersectionRecord] = {}
        self._global_lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────

    def ingest(self, state: IntersectionTrafficState) -> IngestResult:
        """
        Ingest a validated traffic state from Dev 2.
        
        Returns an IngestResult indicating success/rejection and metadata.
        
        Thread-safe: acquires per-intersection lock.
        """
        record = self._get_or_create_record(state.intersection_id)

        with record._lock:
            return self._process_state(record, state)

    def get_current_state(
        self, intersection_id: str
    ) -> Optional[IntersectionTrafficState]:
        """Return the current state for an intersection (or None)."""
        record = self._records.get(intersection_id)
        return record.current_state if record else None

    def get_previous_state(
        self, intersection_id: str
    ) -> Optional[IntersectionTrafficState]:
        """Return the previous state for an intersection (or None)."""
        record = self._records.get(intersection_id)
        return record.previous_state if record else None

    def is_stale(self, intersection_id: str) -> bool:
        """Check if an intersection's state has gone stale."""
        record = self._records.get(intersection_id)
        if record is None or record.last_updated is None:
            return True
        elapsed = (
            datetime.now(timezone.utc) - record.last_updated
        ).total_seconds()
        return elapsed > settings.STALENESS_THRESHOLD_SEC

    def can_switch_sector(
        self, intersection_id: str, proposed_sector: str
    ) -> bool:
        """
        Check if enough dwell time has elapsed to allow a sector switch.
        
        Returns True if:
          • No sector is currently active, OR
          • The proposed sector is the same as the active one, OR
          • The minimum dwell time has elapsed.
        """
        record = self._records.get(intersection_id)
        if record is None or record.active_sector is None:
            return True
        if record.active_sector == proposed_sector:
            return True
        if record.sector_since is None:
            return True
        elapsed = (
            datetime.now(timezone.utc) - record.sector_since
        ).total_seconds()
        return elapsed >= settings.MIN_DWELL_TIME_SEC

    def set_active_sector(
        self, intersection_id: str, sector_id: str
    ) -> None:
        """
        Record which sector is currently GREEN.
        
        Called by the decision engine (Phase 3+) after selecting a sector.
        """
        record = self._records.get(intersection_id)
        if record is None:
            return
        with record._lock:
            if record.active_sector != sector_id:
                record.active_sector = sector_id
                record.sector_since = datetime.now(timezone.utc)

    def get_all_intersection_ids(self) -> list[str]:
        """Return all known intersection IDs."""
        return list(self._records.keys())

    def get_record_stats(self, intersection_id: str) -> Optional[dict]:
        """Return diagnostic stats for an intersection."""
        record = self._records.get(intersection_id)
        if record is None:
            return None
        return {
            "intersection_id": intersection_id,
            "frame_count": record.frame_count,
            "skipped_frames": record.skipped_frames,
            "active_sector": record.active_sector,
            "is_stale": self.is_stale(intersection_id),
            "last_updated": (
                record.last_updated.isoformat() if record.last_updated else None
            ),
        }

    # ── Internals ────────────────────────────────────────────────────────

    def _get_or_create_record(
        self, intersection_id: str
    ) -> IntersectionRecord:
        """Lazily create an IntersectionRecord (thread-safe)."""
        if intersection_id not in self._records:
            with self._global_lock:
                # Double-check after acquiring global lock.
                if intersection_id not in self._records:
                    self._records[intersection_id] = IntersectionRecord()
        return self._records[intersection_id]

    def _process_state(
        self,
        record: IntersectionRecord,
        state: IntersectionTrafficState,
    ) -> "IngestResult":
        """
        Core state transition logic.  Must be called under record._lock.
        
        Steps:
          1. Temporal validation (reject out-of-order).
          2. Skipped-frame detection.
          3. State promotion (current → previous, new → current).
          4. Sync to external store.
        """
        now = datetime.now(timezone.utc)

        # ── 1. Temporal validation ───────────────────────────────────────
        incoming_ts = state.timestamp
        if incoming_ts.tzinfo is None:
            # Assume UTC if no timezone provided.
            incoming_ts = incoming_ts.replace(tzinfo=timezone.utc)

        if record.current_state is not None:
            prev_ts = record.current_state.timestamp
            if prev_ts.tzinfo is None:
                prev_ts = prev_ts.replace(tzinfo=timezone.utc)

            if incoming_ts <= prev_ts:
                logger.warning(
                    "Rejected out-of-order frame for %s: "
                    "incoming=%s <= current=%s",
                    state.intersection_id,
                    incoming_ts.isoformat(),
                    prev_ts.isoformat(),
                )
                return IngestResult(
                    accepted=False,
                    intersection_id=state.intersection_id,
                    reason="out_of_order_timestamp",
                    frame_count=record.frame_count,
                )

            # ── 2. Skipped-frame detection ───────────────────────────────
            gap = (incoming_ts - prev_ts).total_seconds()
            if gap > settings.MAX_FRAME_GAP_SEC:
                record.skipped_frames += 1
                logger.info(
                    "Skipped frame detected for %s: gap=%.2fs (threshold=%.2fs). "
                    "Carrying forward previous state.",
                    state.intersection_id,
                    gap,
                    settings.MAX_FRAME_GAP_SEC,
                )

        # ── 3. State promotion ───────────────────────────────────────────
        record.previous_state = record.current_state
        record.current_state = state
        record.last_updated = now
        record.frame_count += 1

        # ── 4. Sync to external store ────────────────────────────────────
        try:
            self._store.sync_intersection_state(
                state.intersection_id, state
            )
        except Exception:
            logger.exception(
                "Failed to sync state for %s to store. "
                "State accepted locally but not persisted.",
                state.intersection_id,
            )

        logger.debug(
            "Accepted frame #%d for %s (ts=%s)",
            record.frame_count,
            state.intersection_id,
            incoming_ts.isoformat(),
        )

        return IngestResult(
            accepted=True,
            intersection_id=state.intersection_id,
            reason="accepted",
            frame_count=record.frame_count,
            skipped_frames=record.skipped_frames,
            is_stale=False,
        )


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                       INGEST RESULT                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@dataclass
class IngestResult:
    """Returned by IntersectionStateManager.ingest()."""
    accepted: bool
    intersection_id: str
    reason: str
    frame_count: int = 0
    skipped_frames: int = 0
    is_stale: bool = False
