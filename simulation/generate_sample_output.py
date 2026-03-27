import json
import os
from datetime import datetime, timezone

def generate_sample():
    # Intersection INT_001 (Main Junction) config
    intersection_id = "INT_001"
    
    output = {
        "intersection_id": intersection_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lanes": [
            {
                "lane_id": "NORTH_IN",
                "in_density": 12,
                "out_density": 2,
                "capacity": 15,
                "avg_speed": 18.5,
                "queue_length": 8,
                "flow_score": 0.64  # 12 * (1 - 2/15) / 15 (normalized approx)
            },
            {
                "lane_id": "SOUTH_IN",
                "in_density": 14,
                "out_density": 3,
                "capacity": 15,
                "avg_speed": 15.2,
                "queue_length": 10,
                "flow_score": 0.74
            },
            {
                "lane_id": "EAST_IN",
                "in_density": 4,
                "out_density": 1,
                "capacity": 12,
                "avg_speed": 42.0,
                "queue_length": 1,
                "flow_score": 0.30
            },
            {
                "lane_id": "WEST_IN",
                "in_density": 5,
                "out_density": 2,
                "capacity": 12,
                "avg_speed": 38.5,
                "queue_length": 2,
                "flow_score": 0.34
            }
        ],
        "sectors": [
            {
                "sector_id": "NORTH_SOUTH",
                "aggregated_density": 26,
                "avg_speed": 16.85
            },
            {
                "sector_id": "EAST_WEST",
                "aggregated_density": 9,
                "avg_speed": 40.25
            }
        ],
        "emergency_state": {
            "active": True,
            "vehicle_id": "AMB_007",
            "type": "ambulance",
            "distance_to_intersection": 150.5,
            "estimated_arrival_sec": 12.0,
            "priority": 10,
            "vehicles": [
                {
                    "id": "AMB_007",
                    "type": "ambulance",
                    "centroid": [1200, 450],
                    "velocity": [45, 0]
                }
            ]
        },
        "city_state": {
            "status": "online",
            "global_metrics": {
                "total_vehicles": 137,
                "avg_congestion": 0.42
            }
        },
        "routes": [
            {
                "route_id": "R_EMERGENCY_001",
                "path": ["INT_001", "INT_002", "INT_003"],
                "total_distance": 1250,
                "estimated_time_sec": 85.0
            }
        ]
    }
    
    # Save to file
    output_path = "dev2_sample_output.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"Sample output generated at: {os.path.abspath(output_path)}")

if __name__ == "__main__":
    generate_sample()
