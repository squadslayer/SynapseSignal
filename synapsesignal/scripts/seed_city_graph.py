import json
import os
import psycopg2
from psycopg2.extras import execute_values
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / "Synapse-Signal---Backend-" / "control_engine" / ".env"
load_dotenv(dotenv_path=env_path)

DB_CONF = {
    "host": os.getenv("SYNAPSE_DB_HOST", "localhost"),
    "port": os.getenv("SYNAPSE_DB_PORT", "5432"),
    "database": os.getenv("SYNAPSE_DB_NAME", "synapsesignal"),
    "user": os.getenv("SYNAPSE_DB_USER", "synapse_user"),
    "password": os.getenv("SYNAPSE_DB_PASS", "heisenberg")
}

CONFIG_PATH = Path(__file__).parent.parent.parent / "India_Innovates-Dev-2-pipeline-" / "config" / "intersection_config.json"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "synapsesignal" / "database" / "schema.sql"

def seed():
    print(f"Starting Database Seed from {CONFIG_PATH}")
    
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    conn = psycopg2.connect(**DB_CONF)
    cur = conn.cursor()

    try:
        # 1. Reset Schema (Drop and Recreate to apply SERIAL -> VARCHAR changes)
        print("Resetting schema...")
        # We drop in reverse order of dependencies
        drop_tables = [
            "signal_logs", "corridor_logs", "route_nodes", "routes", 
            "emergency_events", "lane_metrics", "traffic_states", 
            "lanes", "roads", "intersections"
        ]
        for table in drop_tables:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
        
        # Run schema.sql
        with open(SCHEMA_PATH, 'r') as f:
            cur.execute(f.read())
        print("Schema created.")

        # 2. Seed Intersections
        print("Seeding intersections...")
        intersections = []
        for int_id, data in config.get("all_intersections_geo", {}).items():
            intersections.append((
                int_id, 
                data['name'], 
                data['latitude'], 
                data['longitude'], 
                json.dumps({}) # empty config for now
            ))
        
        execute_values(cur, 
            "INSERT INTO intersections (intersection_id, name, latitude, longitude, configuration) VALUES %s", 
            intersections
        )

        # 3. Seed Roads
        print("Seeding roads...")
        roads = []
        for road in config.get("roads", []):
            roads.append((
                road['road_id'],
                road.get('name', f"Road {road['road_id']}"),
                road['from_intersection'],
                road['to_intersection'],
                road['distance'],
                60 # default speed limit
            ))
        
        execute_values(cur, 
            "INSERT INTO roads (road_id, name, start_intersection_id, end_intersection_id, length_meters, speed_limit) VALUES %s", 
            roads
        )

        # 4. Seed Lanes
        print("Seeding lanes...")
        lanes_batch = []
        for intersection in config.get("intersections", []):
            int_id = intersection["intersection_id"]
            for lane in intersection.get("lanes", []):
                # Uniquify lane_id by intersection
                unique_lane_id = f"{int_id}_{lane['lane_id']}"
                lanes_batch.append((
                    unique_lane_id, 
                    None, # road_id placeholder
                    int_id, 
                    1, # lane_number placeholder
                    lane['direction'],
                    lane.get('lane_type', 'straight'),
                    lane['capacity']
                ))
        
        execute_values(cur, 
            "INSERT INTO lanes (lane_id, road_id, intersection_id, lane_number, direction, lane_type, width_meters) VALUES %s", 
            lanes_batch
        )
            
        conn.commit()
        print("Database Seeded Successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Seed Failed: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    seed()
