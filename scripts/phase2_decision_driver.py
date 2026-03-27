import json
import requests
import time
from datetime import datetime, timezone
import sys
import os

# Add Dev 2 pipeline to path
sys.path.append(os.path.join(os.getcwd(), "India_Innovates-Dev-2-pipeline-"))
from pipeline import SynapseSignalPipeline

# Backend configuration
BACKEND_URL = "http://localhost:8001/api/v1"

def run_simulation():
    print("Starting Phase 2: Decision Integration Simulation")
    print("-" * 60)
    
    # Initialize Dev 2 Pipeline
    pipeline = SynapseSignalPipeline()
    
    # 1. Mock Dev 1 Detections (Simulation of Stage 1)
    # We'll simulate a heavy North-South load and an approaching ambulance
    mock_dev1_json = {
        "intersection_id": "INT_001",
        "timestamp": time.time(),
        "frame_id": 1,
        "normal_count": 13,
        "emergency_count": 1,
        "details": [  # Ingestor expects 'details' or 'detections'
            # 5 vehicles in NORTH_LIN (mapped to NORTH_IN ROI)
            {"type": "normal_vehicle", "bbox": [400, 100, 450, 150], "confidence": 0.95, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [410, 160, 460, 210], "confidence": 0.92, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [420, 220, 480, 280], "confidence": 0.88, "subtype": "truck"},
            {"type": "normal_vehicle", "bbox": [405, 290, 455, 340], "confidence": 0.94, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [415, 350, 465, 400], "confidence": 0.96, "subtype": "car"},
            
            # 7 vehicles in SOUTH_IN
            {"type": "normal_vehicle", "bbox": [1100, 600, 1150, 650], "confidence": 0.98, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [1110, 660, 1180, 750], "confidence": 0.91, "subtype": "bus"},
            {"type": "normal_vehicle", "bbox": [1120, 760, 1170, 810], "confidence": 0.89, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [1105, 820, 1155, 870], "confidence": 0.93, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [1115, 880, 1165, 930], "confidence": 0.95, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [1125, 940, 1175, 990], "confidence": 0.92, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [1135, 1000, 1185, 1050], "confidence": 0.94, "subtype": "car"},
            
            # 2 vehicles in EAST_IN (Low load)
            {"type": "normal_vehicle", "bbox": [1400, 400, 1450, 450], "confidence": 0.96, "subtype": "car"},
            {"type": "normal_vehicle", "bbox": [1410, 460, 1460, 510], "confidence": 0.93, "subtype": "car"},
            
            # THE AMBULANCE (SOUTH_IN)
            {
                "type": "emergency_vehicle", 
                "bbox": [1120, 1100, 1180, 1160], 
                "confidence": 0.99, 
                "subtype": "ambulance",
                "vehicle_id": "AMB_007"
            }
        ]
    }

    print("Step 1: Running Dev 2 Pipeline (Tracking + Lane Mapping + Metrics)")
    dev2_output = pipeline.process_frame(mock_dev1_json)
    
    # 3. Transform to exact Backend Schema (IntersectionTrafficState)
    lanes_payload = []
    for lane in dev2_output["lanes"]:
        lanes_payload.append({
            "lane_id": lane["lane_id"],
            "in_density": float(lane["in_density"]),
            "out_density": float(lane.get("out_density", 0.0)),
            "capacity": float(max(lane.get("capacity", 15.0), 1.0)),
            "avg_speed": float(lane.get("avg_speed", 0.0)),
            "queue_length": float(lane.get("queue_length", 0.0))
        })
    
    sectors_payload = []
    for s_conf in pipeline.intersection_config["sectors"]:
        agg_density = 0.0
        for s_out in dev2_output["sectors"]:
            if s_out["sector_id"] == s_conf["sector_id"]:
                agg_density = float(s_out["aggregated_density"])
                break
        
        sectors_payload.append({
            "sector_id": s_conf["sector_id"],
            "lanes": s_conf["lanes"],
            "aggregated_density": agg_density
        })

    # Prepare Emergency State
    emergency_active = dev2_output["emergency_state"]["active"]
    emergency_payload = {"active": False}
    if emergency_active:
        ev = dev2_output["emergency_state"]["vehicles"][0]
        emergency_payload = {
            "active": True,
            "vehicle_type": ev["vehicle_type"],
            "vehicle_id": str(ev.get("track_id", "AMB_UNK")),
            "lane_id": ev.get("lane_id", "SOUTH_IN"),
            "velocity": float(ev.get("velocity", 45.0))
        }

    # Wrap in 'payload' for FastAPI decide endpoint
    full_request_payload = {
        "payload": {
            "intersection_id": dev2_output["intersection_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lanes": lanes_payload,
            "sectors": sectors_payload,
            "emergency_state": emergency_payload
        },
        "route_data": None
    }
    
    print(f"Step 2: Sending POST /api/v1/decide to Backend")
    try:
        response = requests.post(f"{BACKEND_URL}/decide", json=full_request_payload, timeout=5)
        if response.status_code == 422:
            print("Error 422: Detail:", response.json())
            return
            
        response.raise_for_status()
        decision = response.json()
        
        print("\n" + "="*60)
        print("PHASE 2 SUCCESS: UNIFIED SYSTEM DECISION")
        print("="*60)
        print(f"Intersection: {decision['intersection_id']}")
        print(f"Selected Sector: {decision['selected_sector']}")
        
        # Check if emergency override was triggered
        mode = "NORMAL"
        if decision.get("corridor") or decision["selected_sector"] == "EMERGENCY_CORRIDOR":
            mode = "EMERGENCY_OVERRIDE"
            
        print(f"Decision Mode: {mode}")
        print("-" * 60)
        print("Signals:")
        for sig in decision['signals']:
            color = sig['state']
            print(f"  - {sig['lane_id']}: {color}")
            
        print("-" * 60)
        print(f"Timing: Green={decision['timing']['green_time']}s, Cycle={decision['timing']['cycle_length']}s")
        
    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to Backend. Is the server running on http://localhost:8001?")
    except Exception as e:
        print(f"\nUnexpected Error type: {type(e)}")
        print(f"Error details: {e}")

if __name__ == "__main__":
    run_simulation()
