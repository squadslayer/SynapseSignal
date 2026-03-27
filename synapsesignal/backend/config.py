# SynapseSignal — Backend Configuration Module
# Designed to be "plugged in" to Dev 3
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Config:
    # 🔗 PostgreSQL
    DB_URI = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    
    # ⚡ Redis
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    
    # 🛡️ Security
    SECRET_KEY = os.getenv('PROJECT_SECRET_KEY')
    
    # 🔑 Redis Key Templates (Plug & Play)
    # Use .format(id=...) or .format(name=...) on these strings
    REDIS_KEYS = {
        "INTERSECTION_STATE": "intersection:{id}:state",
        "LANE_METRICS": "lane:{id}:metrics",
        "EMERGENCY_ACTIVE": "emergency:{id}:active",
        "CORRIDOR_CONGESTION": "corridor:{name}:active",
        "SIGNAL_OVERRIDE": "signal:{id}:override"
    }

    @staticmethod
    def get_key(pattern_name, **kwargs):
        """Helper to generate keys consistently across the backend."""
        template = Config.REDIS_KEYS.get(pattern_name)
        if not template:
            raise ValueError(f"Key pattern '{pattern_name}' not defined.")
        return template.format(**kwargs)
