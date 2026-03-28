import os
import sys
import json
import time
import requests
import traci
import sumolib

# --- Configuration ---
SUMO_BIN_DIR = r"C:\Users\Krishna Sharma\AppData\Local\Programs\Python\Python313\Lib\site-packages\sumo\bin"
SUMO_BINARY = os.path.join(SUMO_BIN_DIR, "sumo.exe")
SUMO_CONFIG = "simulation/sumo/delhi.sumocfg"
BACKEND_URL = "http://localhost:8000/api/v1/ingest"
STATUS_URL = "http://localhost:8000/api/v1/status"

if "SUMO_HOME" not in os.environ:
    os.environ["SUMO_HOME"] = r"C:\Users\Krishna Sharma\AppData\Local\Programs\Python\Python313\Lib\site-packages\sumo"

def get_intersection_data():
    lanes = ["n2c_0", "n2c_1", "n2c_2", "e2c_0", "e2c_1", "e2c_2"]
    intersections = [{
        "id": "AIIMS_CIRCLE",
        "lanes": [],
        "signal": { "north_south": "RED", "east_west": "RED", "mode": "SUMO_CONTROL" }
    }]
    for lane in lanes:
        density = traci.lane.getLastStepVehicleNumber(lane)
        flow_score = traci.lane.getLastStepMeanSpeed(lane) / 13.89
        intersections[0]["lanes"].append({
            "lane_id": lane,
            "in_density": density,
            "flow_score": round(flow_score, 2)
        })
    state = traci.trafficlight.getRedYellowGreenState("center")
    intersections[0]["signal"]["north_south"] = "GREEN" if "G" in state[0:3] else "RED"
    intersections[0]["signal"]["east_west"] = "GREEN" if "G" in state[3:6] else "RED"
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "intersections": intersections,
        "metrics": { "vehicle_count": traci.simulation.getMinExpectedNumber(), "decision_latency": 15, "tracking_accuracy": 0.99 }
    }

def run_simulation_loop():
    print("Starting Infinite SUMO-Synapse Bridge...")
    while True: # 🔄 PERSISTENT LOOP
        try:
            traci.start([SUMO_BINARY, "-c", SUMO_CONFIG, "--no-step-log", "--no-warnings"])
            step = 0
            while traci.simulation.getMinExpectedNumber() > 0:
                traci.simulationStep()
                if step % 10 == 0:
                    try:
                        # 1. Push Telemetry to Backend
                        payload = get_intersection_data()
                        requests.post(BACKEND_URL, json=payload, timeout=0.1)
                        
                        # 2. Pull Feedback from Backend (Signal Overrides)
                        # We use the existing status endpoint to see if an override is active
                        # Note: In a production system we'd use WebSockets or a dedicated Command Queue
                        state_resp = requests.get(STATUS_URL, timeout=0.1)
                        if state_resp.ok:
                            remote_state = state_resp.json()
                            intersection = remote_state.get("intersections", [{}])[0]
                            if intersection.get("signal", {}).get("mode") == "MANUAL_OVERRIDE":
                                # Force SUMO to GREEN for North-South
                                traci.trafficlight.setRedYellowGreenState("center", "GGGGGG") 
                                print("EXTERNAL OVERRIDE DETECTED: FORCING GREEN")
                    except Exception: pass
                step += 1
                time.sleep(0.02)
            traci.close()
            print("Simulation Cycle Finished. Restarting...")
        except Exception as e:
            print(f"TraCI Error: {e}. Retrying in 5s...")
            time.sleep(5)

if __name__ == "__main__":
    run_simulation_loop()
