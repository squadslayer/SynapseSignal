-- SynapseSignal — Base Data Seed Script (Dev 5)

-- Seed Intersections (Example Coordinates for a 4-way Junction)
INSERT INTO intersections (name, latitude, longitude) VALUES
('Park Avenue & 5th St', 28.6139, 77.2090),
('Park Avenue & 6th St', 28.6150, 77.2100),
('Main Road & 5th St', 28.6130, 77.2110),
('Main Road & 6th St', 28.6145, 77.2120);

-- Seed Roads
INSERT INTO roads (name, start_intersection_id, end_intersection_id, length_meters, speed_limit) VALUES
('Park Avenue North', 1, 2, 250, 40),
('5th Street East', 1, 3, 300, 50),
('Main Road North', 3, 4, 350, 60),
('6th Street West', 4, 2, 280, 50);

-- Seed Lanes (2 lanes per road segment)
INSERT INTO lanes (road_id, lane_number, direction, lane_type) VALUES
(1, 1, 'northbound', 'straight'),
(1, 2, 'northbound', 'turn_right'),
(2, 1, 'eastbound', 'straight'),
(2, 2, 'eastbound', 'straight'),
(3, 1, 'northbound', 'straight'),
(3, 2, 'northbound', 'straight'),
(4, 1, 'westbound', 'straight'),
(4, 2, 'westbound', 'turn_left');
