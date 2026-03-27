# SynapseSignal — Live Sync Helper (Dev 5)
import redis
import psycopg2
from psycopg2.extras import execute_values
import json
import time

# Config
REDIS_CONF = {"host": "localhost", "port": 6379, "db": 0}
PG_CONF = {
    "dbname": "synapsesignal",
    "user": "synapse_user",
    "password": "strongpassword",
    "host": "localhost"
}

def sync_lane_metrics():
    """Example function to sync lane metrics from Redis to PG."""
    r = redis.Redis(**REDIS_CONF)
    conn = psycopg2.connect(**PG_CONF)
    cur = conn.cursor()
    
    print("🔄 Scanning Redis for 'lane:*:metrics'...")
    
    # 1. Fetch all lane keys
    for key in r.scan_iter("lane:*:metrics"):
        lane_id = key.decode().split(":")[1]
        data = r.hgetall(key)
        
        # Decode data
        count = int(data.get(b'vehicle_count', 0))
        occupancy = float(data.get(b'occupancy_percent', 0))
        speed = float(data.get(b'avg_speed_kmh', 0))
        
        print(f"  📥 Found Lane {lane_id}: {count} vehicles")
        
        # 2. Insert into PostgreSQL
        cur.execute("""
            INSERT INTO lane_metrics (lane_id, vehicle_count, occupancy_percent, avg_speed_kmh)
            VALUES (%s, %s, %s, %s)
        """, (lane_id, count, occupancy, speed))
    
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Sync complete.")

if __name__ == "__main__":
    # In a real scenario, this would run in a loop or as a cron job
    sync_lane_metrics()
