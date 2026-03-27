"""
SynapseSignal Control Engine — Redis Sync Layer
================================================
Implements the StateStore protocol for real-time state persistence.

Writes to Redis keys:
  • intersection:{id}  — full intersection state (lanes, sectors, signal)
  • signal:{id}        — current signal decision

Design:
  • Graceful degradation: logs warnings but never crashes if Redis is down.
  • Configurable via settings (host, port, db, password).
  • Dependency-injectable: the StateStore protocol allows swapping to
    InMemoryStore for testing with zero Redis dependency.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import redis

from config import settings
from schemas import IntersectionTrafficState

logger = logging.getLogger(__name__)


class RedisSync:
    """
    Production StateStore backed by Redis.
    
    Usage:
        sync = RedisSync()          # connects using settings
        sync.sync_intersection_state("INT_01", state)
        live = sync.get_live_state("INT_01")
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db: int | None = None,
        password: str | None = None,
    ) -> None:
        self._host = host or settings.REDIS_HOST
        self._port = port or settings.REDIS_PORT
        self._db = db if db is not None else settings.REDIS_DB
        self._password = password or settings.REDIS_PASSWORD
        self._client: Optional[redis.Redis] = None

    # ── Connection management ────────────────────────────────────────────

    def connect(self) -> None:
        """Establish a connection to Redis."""
        try:
            self._client = redis.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=2,
            )
            self._client.ping()
            logger.info(
                "Connected to Redis at %s:%d (db=%d)",
                self._host, self._port, self._db,
            )
        except redis.ConnectionError:
            logger.warning(
                "Could not connect to Redis at %s:%d. "
                "State will be managed locally only.",
                self._host, self._port,
            )
            self._client = None

    def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._client:
            self._client.close()
            self._client = None

    @property
    def is_connected(self) -> bool:
        """Check if Redis is reachable."""
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except (redis.ConnectionError, redis.TimeoutError):
            return False

    # ── StateStore protocol methods ──────────────────────────────────────

    def sync_intersection_state(
        self, intersection_id: str, state: IntersectionTrafficState
    ) -> None:
        """
        Write the full intersection state to Redis.
        
        Key: intersection:{intersection_id}
        Value: JSON of lanes, sectors, emergency_state, timestamp
        """
        if self._client is None:
            logger.debug(
                "Redis not connected — skipping sync for %s",
                intersection_id,
            )
            return

        key = f"intersection:{intersection_id}"
        payload = {
            "intersection_id": intersection_id,
            "timestamp": state.timestamp.isoformat(),
            "lanes": [lane.model_dump(mode="json") for lane in state.lanes],
            "sectors": [
                sector.model_dump(mode="json") for sector in state.sectors
            ],
            "emergency_state": state.emergency_state.model_dump(mode="json"),
        }

        try:
            self._client.set(key, json.dumps(payload))
            logger.debug("Synced intersection state → %s", key)
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning(
                "Redis write failed for %s — state not persisted", key
            )

    def sync_signal_state(
        self,
        intersection_id: str,
        sector: str,
        state: str,
        timestamp: str,
    ) -> None:
        """
        Write the current signal decision to Redis.
        
        Key: signal:{intersection_id}
        Value: JSON with sector, state (GREEN/RED/YELLOW), timestamp
        
        Called by the decision engine (Phase 3+) after computing signals.
        """
        if self._client is None:
            return

        key = f"signal:{intersection_id}"
        payload = {
            "sector": sector,
            "state": state,
            "timestamp": timestamp,
        }

        try:
            self._client.set(key, json.dumps(payload))
            logger.debug("Synced signal state → %s", key)
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning(
                "Redis write failed for %s — signal not persisted", key
            )

    def sync_corridor_state(self, corridor_data: dict) -> None:
        """
        Write active corridor state to Redis.
        
        Key: corridor:active
        Value: JSON with route, current_position, next_intersection
        
        Called during green corridor orchestration (Phase A additions).
        """
        if self._client is None:
            return

        try:
            self._client.set("corridor:active", json.dumps(corridor_data))
            logger.debug("Synced corridor state → corridor:active")
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning("Redis write failed for corridor:active")

    def get_live_state(self, intersection_id: str) -> Optional[dict]:
        """
        Retrieve the live state for an intersection from Redis.
        
        Returns parsed dict or None if key doesn't exist / Redis is down.
        """
        if self._client is None:
            return None

        key = f"intersection:{intersection_id}"
        try:
            raw = self._client.get(key)
            if raw:
                return json.loads(raw)
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning("Redis read failed for %s", key)
        return None

    def get_signal_state(self, intersection_id: str) -> Optional[dict]:
        """Retrieve the current signal state from Redis."""
        if self._client is None:
            return None

        key = f"signal:{intersection_id}"
        try:
            raw = self._client.get(key)
            if raw:
                return json.loads(raw)
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning("Redis read failed for %s", key)
        return None
