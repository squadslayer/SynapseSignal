import requests
import time
import random
import json

API_URL = "http://localhost:8000/api/v1/ingest"

def generate_lane_data():
    return [
        {"lane_id": "NORTH_BOUND", "in_density": random.randint(2, 12), "flow_score": random.uniform(0.1, 0.9)},
        {"lane_id": "SOUTH_BOUND", "in_density": random.randint(2, 12), "flow_score": random.uniform(0.1, 0.9)},
        {"lane_id": "EAST_BOUND", "in_density": random.randint(2, 12), "flow_score": random.uniform(0.1, 0.9)},
        {"lane_id": "WEST_BOUND", "in_density": random.randint(2, 12), "flow_score": random.uniform(0.1, 0.9)},
    ]

def run_simulation():
    print("--- Starting SynapseSignal DELHI Simulation ---")
    print(f"Target: {API_URL}")
    
    emergency_active = False
    emergency_timer = 0
    nodes = ["AIIMS_CIRCLE", "DHAULA_KUAN", "TILAK_MARG"]

    while True:
        # Simulate occasional emergency
        if not emergency_active and random.random() < 0.05:
            emergency_active = True
            emergency_timer = 30
            print("🚑 DELHI EMERGENCY: AMB_007 NEAR AIIMS!")

        emergency_state = {
            "active": emergency_active,
            "vehicle_id": "AMB_007" if emergency_active else "",
            "estimated_arrival_sec": emergency_timer if emergency_active else 0,
            "priority": 1 if emergency_active else 0
        }

        # Send data for multiple nodes
        for node_id in nodes:
            payload = {
                "intersection_id": node_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "lanes": generate_lane_data(),
                "emergency_state": emergency_state
            }

            try:
                response = requests.post(API_URL, json=payload)
                if response.status_code == 200:
                    pass 
                else:
                    print(f"Error [{node_id}]: {response.status_code}")
            except Exception as e:
                print(f"Connection failed: {e}")

        print(f"Broadcast @ {time.strftime('%H:%M:%S')} | Active Nodes: {len(nodes)} | Emergency: {emergency_active}")

        if emergency_active:
            emergency_timer -= 2
            if emergency_timer <= 0:
                emergency_active = False
                print("🏁 Emergency cleared.")

        time.sleep(2)

if __name__ == "__main__":
    run_simulation()
