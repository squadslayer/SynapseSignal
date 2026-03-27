# Redis Key Schema — SynapseSignal Live Sync

This document defines the Redis key structure used by the backend to cache real-time traffic data. These keys are designed for high-frequency updates and subsequent synchronization (flushing) to the PostgreSQL database.

## 🔑 Key Structure & Mapping

| Redis Key Pattern | Type | PostgreSQL Target Table | Description |
|:--- |:--- |:--- |:--- |
| `intersection:{id}:state` | Hash | `traffic_states` | Stores the current signal phase and timing metadata for a junction. |
| `lane:{id}:metrics` | Hash | `lane_metrics` | Live counters for vehicle density, speed, and occupancy per lane. |
| `emergency:{id}:active` | Hash | `emergency_events` | Stores metadata for currently active emergency vehicle priorities. |
| `corridor:{name}:active` | String | `corridor_logs` | Current aggregated congestion level for a named traffic corridor. |
| `signal:{id}:override` | String | `signal_logs` | Temporary flag for manual or emergency preemption overrides. |

## 📊 Data Hash Structures

### 1. Intersection State (`intersection:{id}:state`)
```json
{
    "phase": "2",
    "phase_duration": "45",
    "is_timed": "true",
    "last_update": "2026-03-24T16:40:00Z"
}
```

### 2. Lane Metrics (`lane:{id}:metrics`)
```json
{
    "vehicle_count": "12",
    "occupancy_percent": "65.4",
    "avg_speed_kmh": "34.2"
}
```

### 3. Emergency Event (`emergency:{id}:active`)
```json
{
    "vehicle_type": "ambulance",
    "priority": "1",
    "detected_at": "2026-03-24T16:42:00Z"
}
```

## 🔄 Syncing Logic (Worker)

1. **Write**: Backend (Dev 3) receives data from Computer Vision (Dev 1) and writes/updates Redis hashes using `HSET`.
2. **Buffer**: Data persists in Redis to serve the real-time Dashboard (Dev 4).
3. **Flush**: A background worker (scripts) performs a `SCAN` on keys every $N$ seconds, extracts the values, and performs a bulk `INSERT` into PostgreSQL for historical analysis.
