# SynapseSignal — Unified Pipeline Integration Runner
# End-to-End: Dev 1 -> Dev 2 -> Dev 3
import os
import json
import requests
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

# Paths
WORKSPACE = Path(__file__).parent.parent.parent
DEV1_DIR = WORKSPACE / "dev1_pipeline"
DEV2_DIR = WORKSPACE / "India_Innovates-Dev-2-pipeline-"
BACKEND_URL = "http://127.0.0.1:8001/api/v1/decide"

# Append Module Paths
sys.path.append(str(DEV1_DIR))
sys.path.append(str(DEV2_DIR))

# Import Dev 2 Pipeline
try:
    from pipeline import SynapseSignalPipeline
except ImportError as e:
    print(f"Could not import Dev 2 pipeline: {e}")
    sys.exit(1)

def transform_to_dev3(dev2_output: dict) -> dict:
    """
    Transform Dev 2 output to match Dev 3's IntersectionTrafficState schema.
    Specifically handles timestamp conversion, field naming, and Pydantic constraints.
    """
    # 1. Convert float timestamp to ISO 8601 datetime string
    ts = dev2_output.get("timestamp", time.time())
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    
    # 2. Process Lanes (ensure capacity > 0)
    lanes = []
    for lane in dev2_output.get("lanes", []):
        lanes.append({
            "lane_id": lane.get("lane_id", ""),
            "in_density": lane.get("in_density", 0),
            "out_density": lane.get("out_density", 0),
            "capacity": max(lane.get("capacity", 15.0), 1.0), # Ensure > 0
            "avg_speed": lane.get("avg_speed", 0.0),
            "queue_length": lane.get("queue_length", 0)
        })

    # 3. Process Emergency State (Dev 3 expects single vehicle state)
    d2_em = dev2_output.get("emergency_state", {})
    emergency_state = {"active": False}
    
    if d2_em.get("active") and d2_em.get("vehicles"):
        v = d2_em["vehicles"][0] # Pick the first one for Dev 3
        v_type = v.get("vehicle_type", "ambulance")
        # Map common subtypes to Dev 3 Enums
        if "ambulance" in v_type.lower(): mapped_type = "ambulance"
        elif "police" in v_type.lower(): mapped_type = "police"
        elif "fire" in v_type.lower() or "truck" in v_type.lower(): mapped_type = "fire"
        else: mapped_type = "ambulance"

        emergency_state = {
            "active": True,
            "vehicle_type": mapped_type,
            "vehicle_id": str(v.get("track_id", "EM_001")),
            "lane_id": v.get("lane_id"),
            "velocity": v.get("velocity", 0.0)
        }
        
        # Position mapping if available
        if "centroid" in v:
            emergency_state["position"] = {"lat": 21.147, "lon": 79.090} # Mock for now or extract from city_state

    # 4. Process City State
    d2_city = dev2_output.get("city_state", {"intersections": [], "edges": []})
    
    # Map Intersections: node_id -> intersection_id
    city_intersections = []
    for node in d2_city.get("nodes", []):
        city_intersections.append({
            "intersection_id": node.get("node_id"),
            "latitude": node.get("latitude", 0.0),
            "longitude": node.get("longitude", 0.0),
            "aggregated_density": node.get("aggregated_density", 0.0)
        })

    # Map Edges: from -> from_intersection, to -> to_intersection
    city_edges = []
    for edge in d2_city.get("edges", []):
        city_edges.append({
            "edge_id": edge.get("edge_id"),
            "from_intersection": edge.get("from"),
            "to_intersection": edge.get("to"),
            "distance": edge.get("distance"),
            "vehicle_count": edge.get("vehicle_count", 0),
            "avg_speed": edge.get("avg_speed", 0.0),
            "congestion_level": edge.get("congestion_level", "low")
        })
    
    city_state = {
        "intersections": city_intersections,
        "edges": city_edges
    }

    # 5. Build the final payload
    payload = {
        "intersection_id": dev2_output.get("intersection_id", "INT_001"),
        "timestamp": dt,
        "lanes": lanes,
        "sectors": dev2_output.get("sectors", []),
        "emergency_state": emergency_state,
        "city_state": city_state
    }
    
    return payload

import numpy as np

def make_serializable(obj):
    """Recursively convert NumPy types to standard Python types."""
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return make_serializable(obj.tolist())
    return obj

def run_integration(dev1_json_path: str):
    """Run the integration for a single Dev 1 frame."""
    print(f"🚀 Integrating frame: {Path(dev1_json_path).name}")
    
    # Initialize Dev 2
    pipeline = SynapseSignalPipeline()
    
    # Load Dev 1 data
    with open(dev1_json_path, "r") as f:
        dev1_data = json.load(f)
        
    # Process through Dev 2
    print("  Phase: Running Dev 2 Traffic Intelligence...")
    dev2_output = pipeline.process_frame(dev1_data)
    
    # Transform for Dev 3
    print("  Phase: Reformatting for Dev 3 API...")
    dev3_payload = transform_to_dev3(dev2_output)
    
    # Ensure JSON serializable (convert NumPy types)
    dev3_payload = make_serializable(dev3_payload)
    
    # Post to Dev 3
    print(f"  Phase: Sending to Dev 3 Backend at {BACKEND_URL}...")
    try:
        response = requests.post(BACKEND_URL, json=dev3_payload, timeout=5)
        if response.status_code in [200, 202]:
            print("  ✅ Backend Response: 200 OK")
            print("  Decision Result:", json.dumps(response.json(), indent=2))
        else:
            print(f"  ❌ Backend Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"  ❌ Could not connect to Backend: {e}")

import redis

def run_live_bridge(manual_frame=None):
    """
    Subscribes to 'synapse:frames' on Redis or processes a manual frame.
    """
    # Initialize Dev 2 Pipeline (once)
    pipeline = SynapseSignalPipeline()

    if manual_frame:
        print(f"Manual Mode: Processing {manual_frame}")
        ts = time.time()
        
        from dev1_pipeline import build_model, run_on_image
        client = build_model()
        print("  Calling Dev 1 (Gemini) for detection...")
        detections = run_on_image(manual_frame, client)
        
        # Dev 2 expects a dict with 'detections'
        dev1_data = {
            "source": manual_frame,
            "timestamp": ts,
            "detections": detections
        }
        
        # 1. Process through Dev 2
        dev2_output = pipeline.process_frame(dev1_data)
        
        # 2. Reformat for Dev 3
        dev3_payload = transform_to_dev3(dev2_output)
        dev3_payload = make_serializable(dev3_payload)
        
        # 3. Post to Dev 3
        full_payload = {"payload": dev3_payload, "route_data": None}
        resp = requests.post(BACKEND_URL, json=full_payload, timeout=5)
        latency = (time.time() - ts) * 1000
        
        if resp.status_code in [200, 202]:
            print(f"  Forwarded in {latency:.1f}ms | Response: 200 OK")
        else:
            print(f"  Forwarding Error {resp.status_code}: {resp.text}")
        return

    print("SynapseSignal Integration Bridge - Listening for real-time frames...")
    # ... (rest of Redis loop)

if __name__ == "__main__":
    import sys
    # Load env for Redis config
    from dotenv import load_dotenv
    load_dotenv(DEV2_DIR / ".env") # Reuse Dev 2/3 env
    
    manual = sys.argv[1] if len(sys.argv) > 1 else None
    run_live_bridge(manual_frame=manual)
