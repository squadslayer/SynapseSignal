from fastapi import APIRouter
from backend.core.state import update_state

router = APIRouter()

@router.post("/api/v1/ingest")
async def ingest(data: dict):
    state = update_state(data)
    return {"status": "ok", "updated": True}
