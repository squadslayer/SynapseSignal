# SynapseSignal — Connectivity Test Script (Dev 5)
import psycopg2
import redis
import os
from dotenv import load_dotenv

# Load environment variables if .env exists
load_dotenv()

def test_postgres():
    print("--- Testing PostgreSQL Connection ---")
    try:
        # Defaults based on PDF (Page 23)
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "synapsesignal"),
            user=os.getenv("DB_USER", "synapse_user"),
            password=os.getenv("DB_PASS", "strongpassword"),
            host=os.getenv("DB_HOST", "localhost")
        )
        print("✅ PostgreSQL connected successfully!")
        
        # Verify schema
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
        tables = cur.fetchall()
        print(f"📊 Tables found: {len(tables)}")
        for t in tables:
            print(f" - {t[0]}")
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ PostgreSQL Connection Failed: {e}")

def test_redis():
    print("\n--- Testing Redis Connection ---")
    try:
        r = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=0
        )
        response = r.ping()
        if response:
            print("✅ Redis connected successfully (PONG)!")
        else:
            print("⚠️ Redis ping failed.")
    except Exception as e:
        print(f"❌ Redis Connection Failed: {e}")

if __name__ == "__main__":
    test_postgres()
    test_redis()
