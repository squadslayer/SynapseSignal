-- SynapseSignal — Database Schema (Dev 5)
-- PostgreSQL DDL Script

-- 1. Intersections
CREATE TABLE IF NOT EXISTS intersections (
    intersection_id VARCHAR(100) PRIMARY KEY, -- 'INT_001' etc.
    name VARCHAR(100) NOT NULL,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    configuration JSONB, -- For signal timings etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Roads
CREATE TABLE IF NOT EXISTS roads (
    road_id VARCHAR(100) PRIMARY KEY, -- 'R001' etc.
    name VARCHAR(100),
    start_intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    end_intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    length_meters DECIMAL(10, 2),
    speed_limit INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Lanes
CREATE TABLE IF NOT EXISTS lanes (
    lane_id VARCHAR(100) PRIMARY KEY, -- 'NORTH_IN', 'SOUTH_IN' etc.
    road_id VARCHAR(100) REFERENCES roads(road_id) ON DELETE CASCADE,
    intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    lane_number INTEGER, -- e.g., 1 for leftmost
    direction VARCHAR(20),
    lane_type VARCHAR(50), -- e.g., 'turn_left', 'straight'
    width_meters DECIMAL(4, 2)
);

-- 4. Traffic States
CREATE TABLE IF NOT EXISTS traffic_states (
    state_id SERIAL PRIMARY KEY,
    intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    current_phase INTEGER,
    phase_duration INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Lane Metrics
CREATE TABLE IF NOT EXISTS lane_metrics (
    metric_id SERIAL PRIMARY KEY,
    lane_id VARCHAR(100) REFERENCES lanes(lane_id),
    vehicle_count INTEGER,
    occupancy_percent DECIMAL(5, 2),
    avg_speed_kmh DECIMAL(5, 2),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Emergency Events
CREATE TABLE IF NOT EXISTS emergency_events (
    event_id SERIAL PRIMARY KEY,
    intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    vehicle_type VARCHAR(50), -- ambulance, fire_truck, police
    priority_level INTEGER DEFAULT 1,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cleared_at TIMESTAMP
);

-- 7. Routes
CREATE TABLE IF NOT EXISTS routes (
    route_id SERIAL PRIMARY KEY,
    origin_intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    destination_intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    estimated_travel_time INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. Route Nodes
CREATE TABLE IF NOT EXISTS route_nodes (
    node_id SERIAL PRIMARY KEY,
    route_id INTEGER REFERENCES routes(route_id) ON DELETE CASCADE,
    intersection_id VARCHAR(100) REFERENCES intersections(intersection_id),
    sequence_order INTEGER
);

-- 9. Corridor Logs
CREATE TABLE IF NOT EXISTS corridor_logs (
    log_id SERIAL PRIMARY KEY,
    corridor_name VARCHAR(100),
    average_congestion_level DECIMAL(5, 2),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10. Signal Logs (Decision Audit Trail)
CREATE TABLE IF NOT EXISTS signal_logs (
    log_id SERIAL PRIMARY KEY,
    intersection_id VARCHAR(100), -- Matched with INT_001 etc.
    selected_sector VARCHAR(50),
    reason TEXT,
    mode VARCHAR(50),
    green_time DECIMAL(10, 2),
    metadata_json JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 11. Dataset Metadata
CREATE TABLE IF NOT EXISTS dataset_meta (
    dataset_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    class_list JSONB, -- ['car', 'bus', 'ambulance', ...]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 12. Dataset Samples (Images)
CREATE TABLE IF NOT EXISTS dataset_samples (
    sample_id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES dataset_meta(dataset_id) ON DELETE CASCADE,
    file_path VARCHAR(512) NOT NULL,
    width INTEGER,
    height INTEGER,
    captured_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 13. Dataset Annotations (Bboxes)
CREATE TABLE IF NOT EXISTS dataset_annotations (
    annotation_id SERIAL PRIMARY KEY,
    sample_id INTEGER REFERENCES dataset_samples(sample_id) ON DELETE CASCADE,
    class_name VARCHAR(50),
    x_center DECIMAL(10, 6),
    y_center DECIMAL(10, 6),
    width DECIMAL(10, 6),
    height DECIMAL(10, 6),
    confidence DECIMAL(5, 4) -- Ground truth or high-conf model prediction
);

-- 14. Model Training Runs
CREATE TABLE IF NOT EXISTS model_training_runs (
     run_id SERIAL PRIMARY KEY,
     run_name VARCHAR(100) NOT NULL,
     dataset_id INTEGER REFERENCES dataset_meta(dataset_id),
     epochs INTEGER,
     map50 DECIMAL(10, 6),
     map50_95 DECIMAL(10, 6),
     best_model_path VARCHAR(512),
     metrics_json JSONB, -- Full results.csv data in JSON
     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for Dataset Analytics
CREATE INDEX IF NOT EXISTS idx_samples_dataset ON dataset_samples(dataset_id);
CREATE INDEX IF NOT EXISTS idx_annotations_sample ON dataset_annotations(sample_id);
CREATE INDEX IF NOT EXISTS idx_training_map ON model_training_runs(map50);
