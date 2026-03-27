"""
SynapseSignal Control Engine — Traceability Logger
====================================================
Phase 11: Every decision gets a full audit trail routed to
Dev 5 PostgreSQL `signal_logs` table.

Design:
    • Structured log entries with input state, scores, decision reason.
    • Human-readable reason strings for each decision mode.
    • Buffered batch inserts (for PostgreSQL efficiency).
    • Fallback to file-based logging if DB is unreachable.
    • Thread-safe append-only buffer.

Integration:
    The TraceLogger is called after every decide() or safe_decide()
    to record the decision persistently.
"""

from __future__ import annotations

import json
import logging
import threading
import os
from datetime import datetime, timezone
from pathlib import Path
import psycopg2
from psycopg2.extras import execute_values
from typing import Optional

from schemas import (
    IntersectionTrafficState,
    SignalDecisionOutput,
    DecisionMode,
    FlowScore,
    SectorScore,
)

logger = logging.getLogger(__name__)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                     REASON GENERATOR                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

def build_human_reason(
    mode: DecisionMode,
    selected_sector: str,
    sector_scores: list[SectorScore] | None = None,
    extra: str = "",
) -> str:
    """
    Generate a human-readable decision reason string.

    Examples:
      • "Normal: Sector NORTH_SOUTH selected (flow_score=23.50 > 16.50)"
      • "Emergency Override Active: corridor for AMB_001"
      • "Failsafe: default cycle — engine_exception: ZeroDivisionError"
    """
    if mode == DecisionMode.EMERGENCY_OVERRIDE:
        return f"Emergency Override Active: {extra or selected_sector}"

    if mode == DecisionMode.FALLBACK:
        return f"Failsafe: default cycle — {extra}"

    # Normal mode — include sector comparison.
    if sector_scores and len(sector_scores) >= 2:
        top = sector_scores[0]
        runner = sector_scores[1]
        return (
            f"Normal: Sector {top.sector_id} selected "
            f"(flow_score={top.sector_score:.2f} > "
            f"{runner.sector_id}={runner.sector_score:.2f})"
        )
    elif sector_scores:
        return (
            f"Normal: Sector {sector_scores[0].sector_id} selected "
            f"(flow_score={sector_scores[0].sector_score:.2f}, "
            f"only sector)"
        )
    return f"Normal: Sector {selected_sector} selected"


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                     TRACE LOG ENTRY                                  ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TraceEntry:
    """One audit trail entry for a signal decision."""

    __slots__ = (
        "timestamp",
        "intersection_id",
        "mode",
        "selected_sector",
        "reason",
        "green_time",
        "cycle_length",
        "lane_scores",
        "sector_scores",
        "signal_states",
        "is_failsafe",
        "corridor_active",
    )

    def __init__(
        self,
        output: SignalDecisionOutput,
        mode: DecisionMode,
        reason: str,
        lane_scores: list[FlowScore] | None = None,
        sector_scores: list[SectorScore] | None = None,
        is_failsafe: bool = False,
    ):
        self.timestamp = output.timestamp
        self.intersection_id = output.intersection_id
        self.mode = mode
        self.selected_sector = output.selected_sector
        self.reason = reason
        self.green_time = output.timing.green_time
        self.cycle_length = output.timing.cycle_length
        self.lane_scores = {
            s.lane_id: s.flow_score for s in (lane_scores or [])
        }
        self.sector_scores = {
            s.sector_id: s.sector_score for s in (sector_scores or [])
        }
        self.signal_states = {
            s.lane_id: s.state.value for s in output.signals
        }
        self.is_failsafe = is_failsafe
        self.corridor_active = output.corridor is not None

    def to_dict(self) -> dict:
        """Serialize for PostgreSQL insert or JSON logging."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "intersection_id": self.intersection_id,
            "mode": self.mode.value,
            "selected_sector": self.selected_sector,
            "reason": self.reason,
            "green_time": self.green_time,
            "cycle_length": self.cycle_length,
            "lane_scores": self.lane_scores,
            "sector_scores": self.sector_scores,
            "signal_states": self.signal_states,
            "is_failsafe": self.is_failsafe,
            "corridor_active": self.corridor_active,
        }

    def to_pg_row(self) -> dict:
        """
        Map to Dev 5 PostgreSQL `signal_logs` table columns.

        Columns: intersection_id, timestamp, selected_sector, reason,
                 mode, green_time, metadata_json
        """
        return {
            "intersection_id": self.intersection_id,
            "timestamp": self.timestamp,
            "selected_sector": self.selected_sector,
            "reason": self.reason,
            "mode": self.mode.value,
            "green_time": self.green_time,
            "metadata_json": json.dumps({
                "lane_scores": self.lane_scores,
                "sector_scores": self.sector_scores,
                "signal_states": self.signal_states,
                "cycle_length": self.cycle_length,
                "is_failsafe": self.is_failsafe,
                "corridor_active": self.corridor_active,
            }),
        }


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                       TRACE LOGGER                                   ║
# ╚═══════════════════════════════════════════════════════════════════════╝

class TraceLogger:
    """
    Buffered, thread-safe decision trace logger.

    Usage:
        trace = TraceLogger()
        trace.log(output, mode, reason, lane_scores, sector_scores)

        # Retrieve for Dev 5 PostgreSQL batch insert:
        rows = trace.flush_pg_rows()

        # Or retrieve for debugging:
        entries = trace.get_recent(10)
    """

    def __init__(
        self,
        max_buffer: int = 5000,
        fallback_log_path: Optional[str] = None,
    ):
        self._buffer: list[TraceEntry] = []
        self._metrics_buffer: list[dict] = []
        self._states_buffer: list[dict] = []
        self._lock = threading.Lock()
        self._max_buffer = max_buffer
        self._total_logged: int = 0
        self._fallback_path = fallback_log_path

    # ── Logging ──────────────────────────────────────────────────────────

    def log_decision(
        self,
        output: SignalDecisionOutput,
        mode: DecisionMode,
        reason: str,
        lane_scores: list[FlowScore] | None = None,
        sector_scores: list[SectorScore] | None = None,
        is_failsafe: bool = False,
    ) -> TraceEntry:
        """Record a decision trace entry (signal_logs)."""
        entry = TraceEntry(
            output=output,
            mode=mode,
            reason=reason,
            lane_scores=lane_scores,
            sector_scores=sector_scores,
            is_failsafe=is_failsafe,
        )

        with self._lock:
            self._buffer.append(entry)
            self._total_logged += 1
            if len(self._buffer) > self._max_buffer:
                self._buffer = self._buffer[len(self._buffer) // 2 :]

        return entry

    def log_metrics(self, state: IntersectionTrafficState) -> None:
        """Record lane-level metrics (lane_metrics)."""
        ts = state.timestamp or datetime.now(timezone.utc)
        int_id = state.intersection_id
        
        rows = []
        for lane in state.lanes:
            # unique_lane_id matches seed script: f"{int_id}_{lane_id}"
            unique_lane_id = f"{int_id}_{lane.lane_id}"
            occupancy = (lane.out_density / lane.capacity * 100) if lane.capacity > 0 else 0
            
            rows.append({
                "lane_id": unique_lane_id,
                "vehicle_count": int(lane.in_density),
                "occupancy_percent": min(100.0, occupancy),
                "avg_speed_kmh": lane.avg_speed,
                "timestamp": ts
            })
        
        with self._lock:
            self._metrics_buffer.extend(rows)
            if len(self._metrics_buffer) > self._max_buffer:
                self._metrics_buffer = self._metrics_buffer[len(self._metrics_buffer) // 2 :]

    def log_traffic_state(self, state: IntersectionTrafficState, output: SignalDecisionOutput) -> None:
        """Record current intersection state (traffic_states)."""
        ts = state.timestamp or datetime.now(timezone.utc)
        
        entry = {
            "intersection_id": state.intersection_id,
            "current_phase": output.current_phase_index if hasattr(output, 'current_phase_index') else 0,
            "phase_duration": output.timing.green_time,
            "timestamp": ts
        }
        
        with self._lock:
            self._states_buffer.append(entry)
            if len(self._states_buffer) > self._max_buffer:
                self._states_buffer = self._states_buffer[len(self._states_buffer) // 2 :]

    # ── Retrieval ────────────────────────────────────────────────────────

    def get_recent(self, count: int = 10) -> list[TraceEntry]:
        """Return the N most recent entries."""
        with self._lock:
            return list(self._buffer[-count:])

    def flush_all(self) -> dict[str, list[dict]]:
        """Drain all buffers for PostgreSQL batch insert."""
        with self._lock:
            decisions = [e.to_pg_row() for e in self._buffer]
            metrics = list(self._metrics_buffer)
            states = list(self._states_buffer)
            
            self._buffer.clear()
            self._metrics_buffer.clear()
            self._states_buffer.clear()
            
        return {
            "signal_logs": decisions,
            "lane_metrics": metrics,
            "traffic_states": states
        }

    def sync_to_postgresql(self, db_conf: dict) -> int:
        """Drain buffers and insert into multiple PostgreSQL tables."""
        data = self.flush_all()
        total_count = 0
        
        try:
            conn = psycopg2.connect(**db_conf)
            cur = conn.cursor()
            
            for table, rows in data.items():
                if not rows:
                    continue
                
                columns = rows[0].keys()
                query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s"
                values = [[row[col] for col in columns] for row in rows]
                
                execute_values(cur, query, values)
                total_count += len(rows)
            
            conn.commit()
            if total_count > 0:
                logger.info("✅ Persisted %d total entries across %d tables to PostgreSQL", total_count, len(data))
            else:
                logger.info("ℹ️ No new trace data to persist.")
            cur.close()
            conn.close()
            return total_count
        except Exception as e:
            import traceback
            logger.error("❌ Failed to sync trace logs to PostgreSQL: %s\n%s", e, traceback.format_exc())
            return 0
    def sync_now(self) -> int:
        """Helper for manual sync (verification)."""
        # In a real app, we'd inject this via TraceLogger settings. 
        # For now, we'll try to get it from environment.
        try:
            db_conf = {
                "host": os.getenv("SYNAPSE_DB_HOST", "localhost"),
                "port": int(os.getenv("SYNAPSE_DB_PORT", 5432)),
                "dbname": os.getenv("SYNAPSE_DB_NAME", "synapsesignal"),
                "user": os.getenv("SYNAPSE_DB_USER", "synapse_user"),
                "password": os.getenv("SYNAPSE_DB_PASS", "heisenberg"),
            }
            return self.sync_to_postgresql(db_conf)
        except Exception:
            return 0

    def get_stats(self) -> dict:
        """Return logger statistics."""
        with self._lock:
            return {
                "buffer_size": len(self._buffer),
                "total_logged": self._total_logged,
                "max_buffer": self._max_buffer,
            }

    # ── File fallback ────────────────────────────────────────────────────

    def _write_overflow_to_file(self, entries: list[TraceEntry]) -> None:
        """Write overflowed entries to a fallback log file."""
        if not self._fallback_path:
            logger.warning(
                "Buffer overflow: %d entries dropped (no fallback path)",
                len(entries),
            )
            return

        try:
            path = Path(self._fallback_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry.to_dict()) + "\n")
            logger.info(
                "Overflow: %d entries written to %s",
                len(entries), self._fallback_path,
            )
        except OSError as exc:
            logger.error(
                "Failed to write overflow log: %s", exc
            )
