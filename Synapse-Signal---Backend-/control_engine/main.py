"""
SynapseSignal Control Engine — Application Entry Point
=======================================================
FastAPI application that wires together:
  • Pydantic schema validation
  • State Management Engine
  • Signal Decision Engine + Green Corridor
  • Failsafe Controller (no undefined states)
  • Traceability Logger (decision audit → Dev 5)
  • Redis Sync Layer
  • REST + WebSocket API Routes

Run:
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings
from redis_client import RedisSync
from state_manager import IntersectionStateManager
from corridor_engine import GreenCorridorEngine
from decision_engine import SignalDecisionEngine
from failsafe import FailsafeController
from trace_logger import TraceLogger
from routes import (
    router,
    set_manager,
    set_decision_engine,
    set_failsafe_controller,
    set_trace_logger,
)

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-28s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("synapse.main")

# ── Module-level references (for testing / introspection) ────────────────
redis_sync: RedisSync | None = None
state_manager: IntersectionStateManager | None = None
decision_engine: SignalDecisionEngine | None = None
failsafe_ctrl: FailsafeController | None = None
trace_log: TraceLogger | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup:
      1. Connect to Redis (graceful if unavailable).
      2. Create IntersectionStateManager with Redis as its StateStore.
      3. Create GreenCorridorEngine.
      4. Create SignalDecisionEngine (with corridor engine).
      5. Create FailsafeController (wraps decision engine).
      6. Create TraceLogger (audit trail → Dev 5 PostgreSQL).
      7. Inject all into the API routes.

    Shutdown:
      1. Flush remaining trace logs.
      2. Disconnect from Redis cleanly.
    """
    global redis_sync, state_manager, decision_engine, failsafe_ctrl, trace_log

    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  SynapseSignal Control Engine — Starting")
    logger.info("=" * 60)

    redis_sync = RedisSync()
    redis_sync.connect()

    state_manager = IntersectionStateManager(store=redis_sync)
    corridor_engine = GreenCorridorEngine()
    decision_engine = SignalDecisionEngine(
        state_manager, corridor_engine=corridor_engine,
    )
    failsafe_ctrl = FailsafeController(decision_engine, state_manager)
    trace_log = TraceLogger(
        max_buffer=5000,
        fallback_log_path="logs/trace_overflow.jsonl",
    )

    set_manager(state_manager)
    set_decision_engine(decision_engine)
    set_failsafe_controller(failsafe_ctrl)
    set_trace_logger(trace_log)

    logger.info("Components initialized:")
    logger.info("  ├─ Redis connected:      %s", redis_sync.is_connected)
    logger.info("  ├─ State manager:         ready")
    logger.info("  ├─ Corridor engine:       ready")
    logger.info("  ├─ Decision engine:       ready")
    logger.info("  ├─ Failsafe controller:   ready")
    logger.info("  └─ Trace logger:          ready")
    logger.info("Configuration:")
    logger.info("  ├─ Staleness threshold:   %.1fs", settings.STALENESS_THRESHOLD_SEC)
    logger.info("  ├─ Min dwell time:        %.1fs", settings.MIN_DWELL_TIME_SEC)
    logger.info("  ├─ Max frame gap:         %.1fs", settings.MAX_FRAME_GAP_SEC)
    logger.info("  └─ API prefix:            %s", settings.API_PREFIX)
    logger.info("-" * 60)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Shutting down Control Engine...")
    if trace_log:
        logger.info("Syncing trace logs to PostgreSQL...")
        db_conf = {
            "host": settings.DB_HOST,
            "port": settings.DB_PORT,
            "dbname": settings.DB_NAME,
            "user": settings.DB_USER,
            "password": settings.DB_PASS,
        }
        count = trace_log.sync_to_postgresql(db_conf)
        logger.info("Flushed %d trace entries to database", count)
    if redis_sync:
        redis_sync.disconnect()
    logger.info("Goodbye.")


# ── FastAPI App ──────────────────────────────────────────────────────────
app = FastAPI(
    title="SynapseSignal Control Engine",
    description=(
        "Dev 3 — Real-time traffic control backend.\n\n"
        "Ingests flow-aware traffic intelligence from Dev 2, manages "
        "intersection state with temporal continuity, computes optimal "
        "signal decisions, handles emergency green corridors, and "
        "exposes low-latency REST + WebSocket APIs for Dev 4 "
        "dashboard consumption."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router, prefix=settings.API_PREFIX)


# ── Root redirect to docs ───────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to interactive API docs."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")
if __name__ == "__main__":
    import uvicorn
    # Force 0.0.0.0 to avoid Windows IPv6 resolution issues (localhost -> ::1)
    uvicorn.run(app, host="0.0.0.0", port=8001)
