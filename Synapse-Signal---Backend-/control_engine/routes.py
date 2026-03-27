"""
SynapseSignal Control Engine — API Routes
==========================================
FastAPI router exposing REST + WebSocket endpoints.

Endpoints:
  POST  /api/v1/ingest              — Ingest traffic state from Dev 2
  POST  /api/v1/decide              — Run control cycle (failsafe-wrapped)
  POST  /api/v1/corridor/activate   — Activate green corridor
  POST  /api/v1/corridor/position   — Update vehicle position
  POST  /api/v1/corridor/deactivate — Deactivate corridor
  GET   /api/v1/corridor/status     — Get corridor state
  GET   /api/v1/state/{id}          — Get current state for intersection
  GET   /api/v1/state/{id}/stats    — Get diagnostic stats
  GET   /api/v1/decisions           — Recent decision audit log
  GET   /api/v1/trace               — Trace log stats + recent entries
  GET   /api/v1/failsafe            — Failsafe status
  GET   /api/v1/health              — System health check
  WS    /api/v1/ws/signals          — Real-time signal push to Dev 4
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from schemas import IntersectionTrafficState, SignalDecisionOutput, RouteData, DecisionMode
from state_manager import IntersectionStateManager, IngestResult
from decision_engine import SignalDecisionEngine
from failsafe import FailsafeController
from trace_logger import TraceLogger, build_human_reason

logger = logging.getLogger(__name__)

router = APIRouter()

# ╔═══════════════════════════════════════════════════════════════════════╗
# ║              DEPENDENCY INJECTION  (singletons)                      ║
# ╚═══════════════════════════════════════════════════════════════════════╝

_manager: IntersectionStateManager | None = None
_decision_engine: SignalDecisionEngine | None = None
_failsafe: FailsafeController | None = None
_trace: TraceLogger | None = None

# WebSocket subscribers
_ws_clients: set[WebSocket] = set()


def set_manager(manager: IntersectionStateManager) -> None:
    global _manager
    _manager = manager


def set_decision_engine(engine: SignalDecisionEngine) -> None:
    global _decision_engine
    _decision_engine = engine


def set_failsafe_controller(ctrl: FailsafeController) -> None:
    global _failsafe
    _failsafe = ctrl


def set_trace_logger(trace: TraceLogger) -> None:
    global _trace
    _trace = trace


def get_manager() -> IntersectionStateManager:
    if _manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="State manager not initialized",
        )
    return _manager


def get_decision_engine() -> SignalDecisionEngine:
    if _decision_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Decision engine not initialized",
        )
    return _decision_engine


def get_failsafe() -> FailsafeController:
    if _failsafe is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failsafe controller not initialized",
        )
    return _failsafe


def get_trace() -> TraceLogger:
    if _trace is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trace logger not initialized",
        )
    return _trace


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║               HELPER: Broadcast to WebSocket clients                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

async def _broadcast_signal(output: SignalDecisionOutput) -> None:
    """Push signal decision to all connected WebSocket clients."""
    if not _ws_clients:
        return
    payload = output.model_dump(mode="json")
    data = json.dumps(payload)
    dead: set[WebSocket] = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                     INGESTION ENDPOINT                               ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.post(
    "/ingest",
    summary="Ingest traffic state from Dev 2",
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_traffic_state(
    payload: IntersectionTrafficState,
    manager: IntersectionStateManager = Depends(get_manager),
) -> dict[str, Any]:
    result: IngestResult = manager.ingest(payload)
    if not result.accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": result.reason,
                "intersection_id": result.intersection_id,
            },
        )
    return {
        "status": "accepted",
        "intersection_id": result.intersection_id,
        "frame_count": result.frame_count,
        "skipped_frames": result.skipped_frames,
    }


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                  DECISION ENDPOINT (failsafe-wrapped)                ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.post(
    "/decide",
    summary="[PRIMARY] Ingest + decide in one call (failsafe-wrapped)",
    response_model=SignalDecisionOutput,
)
async def decide(
    payload: IntersectionTrafficState,
    route_data: Optional[RouteData] = None,
    manager: IntersectionStateManager = Depends(get_manager),
    failsafe: FailsafeController = Depends(get_failsafe),
    trace: TraceLogger = Depends(get_trace),
) -> SignalDecisionOutput:
    """
    Primary endpoint: ingest + run full control cycle.

    • Wrapped in failsafe: if anything fails, emits safe default.
    • Every decision is trace-logged for Dev 5 PostgreSQL.
    • Output is broadcast to WebSocket subscribers (Dev 4 real-time).

    This is the MAIN endpoint consumed by the system loop.
    """
    # Ingest first
    result = manager.ingest(payload)
    if not result.accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": result.reason,
                "intersection_id": result.intersection_id,
            },
        )

    # Run failsafe-wrapped decision
    output = failsafe.safe_decide(payload, route_data)

    # Determine mode and build reason for traceability
    if failsafe.is_in_fallback:
        mode = DecisionMode.FALLBACK
        reason = build_human_reason(
            mode, output.selected_sector,
            extra=failsafe.fallback_state.reason if failsafe.fallback_state else "",
        )
    elif output.selected_sector == "EMERGENCY_CORRIDOR":
        mode = DecisionMode.EMERGENCY_OVERRIDE
        reason = build_human_reason(
            mode, output.selected_sector,
            extra=f"corridor for {payload.emergency_state.vehicle_id or 'unknown'}",
        )
    else:
        mode = DecisionMode.NORMAL
        reason = build_human_reason(mode, output.selected_sector)

    # Log to trace
    trace.log_decision(output, mode, reason, is_failsafe=failsafe.is_in_fallback)
    trace.log_metrics(payload)
    trace.log_traffic_state(payload, output)

    # Broadcast to WebSocket clients
    await _broadcast_signal(output)

    return output


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    CORRIDOR ENDPOINTS                                ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.post(
    "/corridor/activate",
    summary="Activate a green corridor for an emergency",
)
async def activate_corridor(
    payload: IntersectionTrafficState,
    route_data: RouteData,
    engine: SignalDecisionEngine = Depends(get_decision_engine),
    manager: IntersectionStateManager = Depends(get_manager),
) -> dict[str, Any]:
    if not payload.emergency_state.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot activate corridor: emergency_state.active is False",
        )

    manager.ingest(payload)
    output = engine.decide(payload, route_data=route_data)

    corridor = engine.corridor_engine
    session = corridor.session

    return {
        "status": "corridor_activated" if corridor.is_active else "activation_failed",
        "route_id": session.selected_route.route_id if session and session.selected_route else None,
        "path": session.route_intersections if session else [],
        "eta_count": len(session.eta_sequence) if session else 0,
        "signal_output": output.model_dump(mode="json"),
    }


@router.post(
    "/corridor/position",
    summary="Update emergency vehicle position",
)
async def update_corridor_position(
    intersection_id: str,
    engine: SignalDecisionEngine = Depends(get_decision_engine),
) -> dict[str, Any]:
    corridor = engine.corridor_engine
    if not corridor.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active corridor",
        )

    corridor.advance_by_intersection_id(intersection_id)
    session = corridor.session

    return {
        "status": "position_updated",
        "passed_intersections": session.passed_intersections if session else [],
        "restoration_queue": corridor.get_restoration_intersections(),
        "current": session.current_intersection if session else None,
        "next": session.next_intersection if session else None,
    }


@router.get(
    "/corridor/status",
    summary="Get active corridor status",
)
async def get_corridor_status(
    engine: SignalDecisionEngine = Depends(get_decision_engine),
) -> dict[str, Any]:
    corridor = engine.corridor_engine
    if not corridor.is_active:
        return {"active": False}

    redis_data = corridor.get_redis_corridor_data()
    output_state = corridor.get_corridor_output_state()

    return {
        "active": True,
        "redis_payload": redis_data,
        "corridor_state": output_state.model_dump(mode="json") if output_state else None,
        "restoration_queue": corridor.get_restoration_intersections(),
        "log_entries_pending": len(corridor._corridor_log),
    }


@router.post(
    "/corridor/deactivate",
    summary="Deactivate the green corridor",
)
async def deactivate_corridor(
    engine: SignalDecisionEngine = Depends(get_decision_engine),
) -> dict[str, Any]:
    corridor = engine.corridor_engine
    if not corridor.is_active:
        return {"status": "no_active_corridor"}
    corridor.deactivate()
    return {
        "status": "corridor_deactivated",
        "restoration_queue": corridor.get_restoration_intersections(),
    }


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                      QUERY ENDPOINTS                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.get(
    "/state/{intersection_id}",
    summary="Get current state for an intersection",
)
async def get_intersection_state(
    intersection_id: str,
    manager: IntersectionStateManager = Depends(get_manager),
) -> dict[str, Any]:
    current = manager.get_current_state(intersection_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No state recorded for intersection '{intersection_id}'",
        )
    return {
        "intersection_id": intersection_id,
        "is_stale": manager.is_stale(intersection_id),
        "current_state": current.model_dump(mode="json"),
    }


@router.get(
    "/state/{intersection_id}/stats",
    summary="Get diagnostic stats for an intersection",
)
async def get_intersection_stats(
    intersection_id: str,
    manager: IntersectionStateManager = Depends(get_manager),
) -> dict[str, Any]:
    stats = manager.get_record_stats(intersection_id)
    if stats is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No record for intersection '{intersection_id}'",
        )
    return stats


@router.get(
    "/decisions",
    summary="Recent decision audit log",
)
async def get_recent_decisions(
    count: int = 10,
    engine: SignalDecisionEngine = Depends(get_decision_engine),
) -> list[dict[str, Any]]:
    entries = engine.get_recent_decisions(count)
    return [e.model_dump(mode="json") for e in entries]


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                TRACEABILITY + FAILSAFE ENDPOINTS                     ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.get(
    "/trace",
    summary="Trace log stats and recent entries",
)
async def get_trace_info(
    count: int = 10,
    trace: TraceLogger = Depends(get_trace),
) -> dict[str, Any]:
    entries = trace.get_recent(count)
    return {
        "stats": trace.get_stats(),
        "recent": [e.to_dict() for e in entries],
    }


@router.post(
    "/trace/flush",
    summary="Flush trace buffer for PostgreSQL batch insert",
)
async def flush_trace(
    trace: TraceLogger = Depends(get_trace),
) -> dict[str, Any]:
    """
    Drain the trace buffer and return rows for Dev 5 PostgreSQL insertion.
    Dev 5 calls this periodically to batch-insert into signal_logs.
    """
    rows = trace.flush_pg_rows()
    return {"flushed_count": len(rows), "rows": rows}


@router.get(
    "/failsafe",
    summary="Failsafe system status",
)
async def get_failsafe_status(
    failsafe: FailsafeController = Depends(get_failsafe),
) -> dict[str, Any]:
    return failsafe.stats


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    WEBSOCKET ENDPOINT                                ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket):
    """
    Real-time signal push to Dev 4 React dashboard.

    Protocol:
      1. Client connects to ws://<host>/api/v1/ws/signals
      2. Server pushes SignalDecisionOutput JSON on every decide() call
      3. Client can send intersection_id to subscribe to a specific
         intersection (future enhancement).

    This is the low-latency channel for Dev 4's real-time visualization.
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info(
        "WebSocket client connected (%d total)", len(_ws_clients)
    )
    try:
        while True:
            # Keep connection alive; client can send pings or commands.
            data = await websocket.receive_text()
            # Future: filter by intersection_id
            logger.debug("WS received: %s", data[:100])
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)
        logger.info(
            "WebSocket client disconnected (%d remaining)", len(_ws_clients)
        )


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                       HEALTH CHECK                                   ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.post(
    "/trace/sync",
    summary="Manual database sync",
)
async def sync_trace() -> dict[str, Any]:
    """Force flush all buffered trace data to PostgreSQL."""
    if not _trace:
        raise HTTPException(status_code=503, detail="Trace logger not initialized")
    
    count = _trace.sync_now()
    return {"status": "success", "flushed_count": count}

@router.get(
    "/health",
    summary="System health check",
)
async def health_check(
    manager: IntersectionStateManager = Depends(get_manager),
) -> dict[str, Any]:
    ids = manager.get_all_intersection_ids()

    # Build comprehensive health report
    health: dict[str, Any] = {
        "status": "healthy",
        "intersections_tracked": len(ids),
        "intersection_ids": ids,
    }

    # Add failsafe status if available
    if _failsafe:
        health["failsafe"] = _failsafe.stats

    # Add trace stats if available
    if _trace:
        health["trace"] = _trace.get_stats()

    # Add corridor status if available
    if _decision_engine:
        corridor = _decision_engine.corridor_engine
        health["corridor_active"] = corridor.is_active

    return health
