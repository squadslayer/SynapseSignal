from fastapi import APIRouter
from backend.core.state import get_state

router = APIRouter()

@router.get("/api/v1/state")
async def state():
    return get_state()
