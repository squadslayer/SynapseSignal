import os
import redis
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Redis Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

def get_redis_client():
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)
