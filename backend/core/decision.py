def compute_signal(lanes):
    ns_flow = 0
    ew_flow = 0

    for lane in lanes:
        lane_id = lane.get("lane_id", "")
        flow_score = lane.get("flow_score", 0)
        
        if "NORTH" in lane_id or "SOUTH" in lane_id:
            ns_flow += flow_score
        else:
            ew_flow += flow_score

    print(f"DEBUG: ns_flow={ns_flow}, ew_flow={ew_flow}")

    if ns_flow >= ew_flow: # Tie-break to NS
        return {
            "north_south": "GREEN",
            "east_west": "RED",
            "mode": "NORMAL"
        }
    else:
        return {
            "north_south": "RED",
            "east_west": "GREEN",
            "mode": "NORMAL"
        }

def apply_emergency_override(signal, emergency):
    if emergency and emergency.get("active"):
        # Support both 'estimated_arrival_sec' and 'eta'
        eta = emergency.get("estimated_arrival_sec", emergency.get("eta", 999))

        if eta < 20:
            return {
                "north_south": "GREEN",
                "east_west": "RED",
                "mode": "EMERGENCY_OVERRIDE"
            }

    return signal
