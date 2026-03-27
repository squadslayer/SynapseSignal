from fastapi import FastAPI
from backend.api import ingest, state, ws
import json
import redis

app = FastAPI()

# Initialize Redis for the main app endpoints
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

app.include_router(ingest.router)
app.include_router(state.router)
app.include_router(ws.router)

@app.post("/api/v1/emergency/trigger")
async def trigger_emergency():
    data_raw = r.get("city_state")
    if not data_raw:
        return {"error": "State not initialized"}
    
    data = json.loads(data_raw)
    data["emergency"]["active"] = True
    data["emergency"]["estimated_arrival_sec"] = 10
    
    r.set("city_state", json.dumps(data))
    
    # Broadcast manually
    from backend.api.ws import manager
    await manager.broadcast(data)
    
    return {"status": "emergency_triggered", "state": data}

@app.post("/api/v1/signal/override")
async def override_signal():
    data_raw = r.get("city_state")
    if not data_raw or not json.loads(data_raw).get("intersections"):
        return {"error": "State not initialized"}
    
    data = json.loads(data_raw)
    data["intersections"][0]["signal"] = {
        "north_south": "GREEN",
        "east_west": "RED",
        "mode": "MANUAL_OVERRIDE"
    }
    
    r.set("city_state", json.dumps(data))
    
    # Broadcast manually
    from backend.api.ws import manager
    await manager.broadcast(data)
    
    return {"status": "manual_override", "state": data}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
