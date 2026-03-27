from backend.core.decision import compute_signal, apply_emergency_override

CURRENT_STATE = {}

def update_state(data):
    global CURRENT_STATE

    print("\n--- INCOMING DATA ---")
    # Using a subset for print readability if data is large
    print(json.dumps(data, indent=2) if isinstance(data, dict) else data)

    lanes = data.get("lanes", [])
    emergency = data.get("emergency_state", {})

    signal = compute_signal(lanes)
    signal = apply_emergency_override(signal, emergency)

    print("\n--- COMPUTED SIGNAL ---")
    print(signal)

    data["signal"] = signal

    CURRENT_STATE = data
    return CURRENT_STATE

def get_state():
    return CURRENT_STATE

import json # Needed for print
