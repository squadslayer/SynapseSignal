"""
Tests for the FastAPI API routes.

Verifies:
  • POST /ingest with valid payload → 200
  • POST /ingest with invalid payload → 422
  • POST /ingest with out-of-order timestamp → 409
  • POST /decide (failsafe-wrapped) → returns SignalDecisionOutput
  • GET /state/{id} returns current state
  • GET /state/{id} returns 404 for unknown
  • GET /health returns comprehensive status
  • GET /trace returns trace stats
  • GET /failsafe returns failsafe status
"""

import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app
from state_manager import IntersectionStateManager, InMemoryStore
from decision_engine import SignalDecisionEngine
from failsafe import FailsafeController
from trace_logger import TraceLogger
from routes import set_manager, set_decision_engine, set_failsafe_controller, set_trace_logger


# ── Fixture ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _setup_all():
    """Inject fresh instances for each test."""
    store = InMemoryStore()
    manager = IntersectionStateManager(store=store)
    engine = SignalDecisionEngine(manager)
    failsafe = FailsafeController(engine, manager)
    trace = TraceLogger()

    set_manager(manager)
    set_decision_engine(engine)
    set_failsafe_controller(failsafe)
    set_trace_logger(trace)
    yield
    set_manager(None)
    set_decision_engine(None)
    set_failsafe_controller(None)
    set_trace_logger(None)


def _valid_payload(ts: datetime | None = None) -> dict:
    if ts is None:
        ts = datetime.now(timezone.utc)
    return {
        "intersection_id": "INT_01",
        "timestamp": ts.isoformat(),
        "lanes": [
            {
                "lane_id": "L1",
                "in_density": 10.0,
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
        "sectors": [
            {
                "sector_id": "NORTH_SOUTH",
                "lanes": ["L1", "L2"],
                "aggregated_density": 18.0,
            }
        ],
        "emergency_state": {"active": False},
    }


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                       INGEST TESTS                                   ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@pytest.mark.asyncio
async def test_ingest_valid_payload():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/ingest", json=_valid_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["frame_count"] == 1


@pytest.mark.asyncio
async def test_ingest_invalid_payload_422():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/ingest", json={"bad": "data"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_capacity_zero_422():
    payload = _valid_payload()
    payload["lanes"][0]["capacity"] = 0
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/ingest", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_out_of_order_409():
    t1 = datetime.now(timezone.utc)
    t2 = t1 - timedelta(seconds=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post("/api/v1/ingest", json=_valid_payload(ts=t1))
        assert resp1.status_code == 202

        resp2 = await client.post("/api/v1/ingest", json=_valid_payload(ts=t2))
        assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_ingest_sequential_frames():
    t = datetime.now(timezone.utc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for i in range(5):
            resp = await client.post(
                "/api/v1/ingest",
                json=_valid_payload(ts=t + timedelta(seconds=i)),
            )
            assert resp.status_code == 202
            assert resp.json()["frame_count"] == i + 1


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    DECIDE ENDPOINT TESTS                             ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@pytest.mark.asyncio
async def test_decide_returns_output():
    """POST /decide should ingest + return signal decision."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # FastAPI embeds both body params, so we need to wrap in keys
        resp = await client.post(
            "/api/v1/decide",
            json={
                "payload": _valid_payload(),
                "route_data": None,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "selected_sector" in body
    assert "signals" in body
    assert "timing" in body


@pytest.mark.asyncio
async def test_decide_via_ingest_first():
    """Ingest then check we can get decisions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/ingest", json=_valid_payload())
        assert resp.status_code == 202
        resp2 = await client.get("/api/v1/decisions?count=5")
        assert resp2.status_code == 200


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║                    STATE QUERY TESTS                                 ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@pytest.mark.asyncio
async def test_get_state_after_ingest():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/ingest", json=_valid_payload())
        resp = await client.get("/api/v1/state/INT_01")
    assert resp.status_code == 200
    assert resp.json()["intersection_id"] == "INT_01"


@pytest.mark.asyncio
async def test_get_state_unknown_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/state/UNKNOWN")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_stats():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/ingest", json=_valid_payload())
        resp = await client.get("/api/v1/state/INT_01/stats")
    assert resp.status_code == 200
    assert resp.json()["frame_count"] == 1


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║               TRACE / FAILSAFE / HEALTH TESTS                       ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@pytest.mark.asyncio
async def test_trace_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/trace?count=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "stats" in body
    assert "recent" in body


@pytest.mark.asyncio
async def test_failsafe_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/failsafe")
    assert resp.status_code == 200
    body = resp.json()
    assert body["in_fallback"] is False


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "failsafe" in body
    assert "trace" in body
