import redis
import json
from backend.core.decision import compute_signal, apply_emergency_override

# Initialize Redis Client
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

async def update_state(data):
    print("\n--- INCOMING DATA ---")
    print("Writing to Redis...")
    
    lanes = data.get("lanes", [])
    emergency = data.get("emergency_state", {})

    signal = compute_signal(lanes)
    signal = apply_emergency_override(signal, emergency)

    print("\n--- COMPUTED SIGNAL ---")
    print(signal)

    # Canonical City Structure
    city_state = {
        "timestamp": data.get("timestamp"),
        "intersections": [
            {
                "id": data.get("intersection_id"),
                "lanes": lanes,
                "signal": signal
            }
        ],
        "emergency": emergency
    }
    
    # Store in Redis
    r.set("city_state", json.dumps(city_state))
    
    # Trigger WebSocket Broadcast
    from backend.api.ws import manager
    await manager.broadcast(city_state)
    
    return city_state

def get_state():
    print("Reading from Redis...")
    data = r.get("city_state")
    return json.loads(data) if data else {}
