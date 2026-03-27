def compute_signal(lanes, emergency):
    ns_flow = 0
    ew_flow = 0
    reasons = []

    for lane in lanes:
        lane_id = lane.get("lane_id", "")
        flow_score = lane.get("flow_score", 0)
        
        if "NORTH" in lane_id or "SOUTH" in lane_id:
            ns_flow += flow_score
        else:
            ew_flow += flow_score

    if ns_flow > ew_flow:
        signal = {
            "north_south": "GREEN",
            "east_west": "RED"
        }
        reasons.append(f"NS flow higher ({ns_flow:.2f} > {ew_flow:.2f})")
    elif ew_flow > ns_flow:
        signal = {
            "north_south": "RED",
            "east_west": "GREEN"
        }
        reasons.append(f"EW flow higher ({ew_flow:.2f} > {ns_flow:.2f})")
    else:
        # Tie-break to NS
        signal = {
            "north_south": "GREEN",
            "east_west": "RED"
        }
        reasons.append(f"Traffic flow balanced ({ns_flow:.2f}). Defaulting to NS priority.")

    confidence = round(abs(ns_flow - ew_flow) / (ns_flow + ew_flow + 0.01), 2)
    # Ensure confidence is between 0 and 1
    confidence = min(max(confidence, 0.45), 1.0) 

    return signal, reasons, confidence

def apply_emergency(signal, emergency, reasons):
    if emergency and emergency.get("active"):
        eta = emergency.get("estimated_arrival_sec", emergency.get("eta", 999))

        if eta < 20:
            reasons.append(f"Emergency override: ETA {eta}s")
            return {
                "north_south": "GREEN",
                "east_west": "RED",
                "mode": "EMERGENCY_OVERRIDE"
            }

    signal["mode"] = "NORMAL"
    return signal
