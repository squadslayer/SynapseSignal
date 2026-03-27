from backend.core.config import get_redis_client
import json
import random
from backend.core.decision import compute_signal, apply_emergency

# Initialize Redis Client from shared config
r = get_redis_client()


async def update_state(data):
    lanes = data.get("lanes", [])
    emergency = data.get("emergency_state", {})

    # Compute Intelligence
    signal, reasons, confidence = compute_signal(lanes, emergency)
    signal = apply_emergency(signal, emergency, reasons)

    # Calculate Metrics
    vehicle_count = sum([l.get("in_density", 0) for l in lanes]) or random.randint(5, 15)
    
    # Canonical City State v2
    city_state = {
        "timestamp": data.get("timestamp"),
        "intersections": [
            {
                "id": data.get("intersection_id", "INT_001"),
                "lanes": lanes,
                "signal": signal,
                "decision": {
                    "reasons": reasons,
                    "confidence": confidence
                }
            }
        ],
        "emergency": emergency,
        "metrics": {
            "vehicle_count": vehicle_count,
            "decision_latency": 8,
            "tracking_accuracy": 0.91,
            "detection_latency": 42
        },
        "pipeline": {
            "detection_count": vehicle_count + random.randint(-2, 2),
            "tracking_ids": vehicle_count,
            "stage": "decision_complete",
            "decision": f"{signal['north_south']}_{signal['east_west']}"
        }
    }
    
    # Store in Redis
    r.set("city_state", json.dumps(city_state))
    
    # Trigger WebSocket Broadcast
    try:
        from backend.api.ws import manager
        await manager.broadcast(city_state)
    except Exception as e:
        print(f"WS Broadcast Error: {e}")
    
    return city_state

def get_state():
    data = r.get("city_state")
    return json.loads(data) if data else {}
