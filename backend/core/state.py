from backend.core.decision import compute_signal, apply_emergency_override

CURRENT_STATE = {}

def update_state(data):
    global CURRENT_STATE

    print("\n--- INCOMING DATA ---")
    print(json.dumps(data, indent=2) if isinstance(data, dict) else data)

    lanes = data.get("lanes", [])
    emergency = data.get("emergency_state", {})

    signal = compute_signal(lanes)
    signal = apply_emergency_override(signal, emergency)

    print("\n--- COMPUTED SIGNAL ---")
    print(signal)

    # Canonical City Structure Refactor
    CURRENT_STATE = {
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
    
    return CURRENT_STATE

def get_state():
    return CURRENT_STATE

import json # Needed for print
