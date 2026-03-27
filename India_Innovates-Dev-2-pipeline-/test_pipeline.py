"""
Dev 2 - Pipeline Tests
Validates each phase and end-to-end pipeline with sample data.
"""

import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.detection_ingestion import DetectionIngestor
from modules.tracker import MultiObjectTracker, compute_iou
from modules.lane_mapper import LaneMapper, point_in_polygon
from modules.lane_metrics import LaneMetricsComputer
from modules.downstream_estimator import DownstreamEstimator
from modules.flow_features import FlowFeatureComputer
from modules.sector_aggregator import SectorAggregator
from modules.intersection_state import IntersectionStateBuilder
from modules.graph_builder import GraphBuilder, CityGraph
from modules.geo_mapper import GeoMapper
from modules.route_engine import RouteEngine
from output_api import OutputAPI
from pipeline import SynapseSignalPipeline


# ===========================================================
# Sample Dev 1 Output (what Dev 1 actually produces)
# ===========================================================

SAMPLE_FRAME_1 = {
    "timestamp": 1774280454.0,
    "time_offset": 0.0,
    "normal_count": 13,
    "emergency_count": 1,
    "details": [
        {"type": "emergency_vehicle", "subtype": "ambulance",
         "bbox": [448, 341, 1040, 773], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [0, 0, 224, 144], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [400, 0, 768, 90], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "minivan",
         "bbox": [992, 9, 1584, 378], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [1408, 90, 1600, 378], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [80, 422, 544, 746], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [576, 233, 992, 539], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [1024, 233, 1472, 530], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "suv",
         "bbox": [927, 387, 1488, 773], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [0, 674, 416, 900], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [400, 720, 880, 900], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [880, 657, 1440, 900], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [1392, 485, 1600, 809], "confidence": 0.99},
        {"type": "normal_vehicle", "subtype": "motorcycle",
         "bbox": [1056, 630, 1584, 900], "confidence": 0.99},
    ],
}

SAMPLE_FRAME_2 = {
    "timestamp": 1774280462.0,
    "time_offset": 8.0,
    "normal_count": 5,
    "emergency_count": 1,
    "details": [
        {"type": "emergency_vehicle", "subtype": "ambulance",
         "bbox": [500, 300, 1100, 750], "confidence": 0.98},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [100, 400, 500, 700], "confidence": 0.95},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [600, 250, 1000, 550], "confidence": 0.97},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [1050, 250, 1500, 550], "confidence": 0.96},
        {"type": "normal_vehicle", "subtype": "car",
         "bbox": [0, 650, 400, 880], "confidence": 0.94},
        {"type": "normal_vehicle", "subtype": "suv",
         "bbox": [950, 400, 1500, 780], "confidence": 0.93},
    ],
}


def test_phase1_detection_ingestion():
    """Test Phase 1: Detection Ingestion."""
    print("TEST: Phase 1 - Detection Ingestion")
    ingestor = DetectionIngestor()

    frame = ingestor.ingest(SAMPLE_FRAME_1)
    assert frame.frame_id == 0, f"Expected frame_id=0, got {frame.frame_id}"
    assert len(frame.objects) == 14, f"Expected 14 objects, got {len(frame.objects)}"
    assert frame.normal_count == 13
    assert frame.emergency_count == 1

    # Check centroid computation
    ambulance = frame.objects[0]
    assert ambulance.is_emergency, "First object should be emergency"
    assert ambulance.subtype == "ambulance"
    expected_cx = (448 + 1040) // 2  # 744
    expected_cy = (341 + 773) // 2   # 557
    assert ambulance.centroid == (expected_cx, expected_cy), \
        f"Centroid should be ({expected_cx}, {expected_cy}), got {ambulance.centroid}"

    # Test summary-only format
    summary_frame = ingestor.ingest({"time_offset": 0.0, "normal_count": 10, "emergency_count": 0})
    assert len(summary_frame.objects) == 0
    assert summary_frame.normal_count == 10

    print("  [X] PASSED\n")


def test_phase2_tracker():
    """Test Phase 2: Multi-Object Tracking."""
    print("TEST: Phase 2 - Multi-Object Tracking")
    ingestor = DetectionIngestor()
    tracker = MultiObjectTracker(track_activation_threshold=0.05, lost_track_buffer=30)

    frame1 = ingestor.ingest(SAMPLE_FRAME_1)
    tracks1 = tracker.update(frame1)
    assert len(tracks1) == 14, f"Expected 14 tracks, got {len(tracks1)}"

    # All detections should have object_ids
    for obj in frame1.objects:
        assert obj.object_id is not None, "All objects should have IDs after tracking"

    frame2 = ingestor.ingest(SAMPLE_FRAME_2)
    tracks2 = tracker.update(frame2)
    # Should have some matched tracks and some new ones
    assert len(tracks2) > 0, "Should have active tracks"

    print(f"  Frame 1: {len(tracks1)} tracks")
    print(f"  Frame 2: {len(tracks2)} tracks")
    print("  [X] PASSED\n")


def test_iou():
    """Test IoU computation."""
    print("TEST: IoU Computation")
    # Perfect overlap
    assert compute_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0

    # No overlap
    assert compute_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0

    # Partial overlap
    iou = compute_iou([0, 0, 10, 10], [5, 5, 15, 15])
    assert 0.1 < iou < 0.2, f"Expected ~0.143, got {iou}"

    print("  [X] PASSED\n")


def test_phase3_lane_mapper():
    """Test Phase 3: Lane Mapping."""
    print("TEST: Phase 3 - Lane Mapping")

    # Test point_in_polygon
    square = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert point_in_polygon((50, 50), square), "Center should be inside"
    assert not point_in_polygon((150, 50), square), "Outside should not be inside"

    # Test with config
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config", "intersection_config.json",
    )
    with open(config_path) as f:
        config = json.load(f)

    lane_mapper = LaneMapper(config["intersections"][0]["lanes"])

    # Ambulance centroid (744, 557) — should be in a lane
    lane = lane_mapper.assign_lane((744, 557))
    print(f"  Ambulance (744, 557) -> lane: {lane}")
    # Should be assigned to some lane

    # Car at (112, 72) — top-left, should be WEST_OUT or NORTH_IN
    lane2 = lane_mapper.assign_lane((112, 72))
    print(f"  Car (112, 72) -> lane: {lane2}")

    print("  [X] PASSED\n")


def test_phase4_lane_metrics():
    """Test Phase 4: Lane Metrics."""
    print("TEST: Phase 4 - Lane Metrics")
    computer = LaneMetricsComputer(stopped_speed_threshold=5.0)

    # Create mock lane assignments
    from modules.tracker import Track
    mock_tracks = {
        "NORTH_IN": [
            Track(track_id=1, bbox=[0,0,10,10], centroid=(5,5),
                  obj_type="normal_vehicle", subtype="car",
                  confidence=0.9, velocity=10.0),
            Track(track_id=2, bbox=[20,20,30,30], centroid=(25,25),
                  obj_type="normal_vehicle", subtype="car",
                  confidence=0.9, velocity=0.0),
        ],
        "SOUTH_IN": [],
    }

    metrics = computer.compute(mock_tracks)
    assert metrics["NORTH_IN"].in_density == 2
    assert metrics["NORTH_IN"].queue_length == 1  # one stopped vehicle
    assert metrics["NORTH_IN"].avg_speed == 5.0   # (10 + 0) / 2
    assert metrics["SOUTH_IN"].in_density == 0

    print(f"  NORTH_IN: density={metrics['NORTH_IN'].in_density}, "
          f"queue={metrics['NORTH_IN'].queue_length}")
    print("  [X] PASSED\n")


def test_phase7_sector_aggregation():
    """Test Phase 7: Sector Aggregation."""
    print("TEST: Phase 7 - Sector Aggregation")

    from modules.lane_metrics import LaneMetrics
    
    mock_metrics = {
        "NORTH_IN": LaneMetrics("NORTH_IN", 5, 10.0, 2, [1,2,3,4,5]),
        "SOUTH_IN": LaneMetrics("SOUTH_IN", 3, 15.0, 1, [6,7,8]),
        "EAST_IN": LaneMetrics("EAST_IN", 4, 8.0, 3, [9,10,11,12]),
        "WEST_IN": LaneMetrics("WEST_IN", 2, 12.0, 0, [13,14]),
    }

    sectors = [
        {"sector_id": "NORTH_SOUTH", "lanes": ["NORTH_IN", "SOUTH_IN"]},
        {"sector_id": "EAST_WEST", "lanes": ["EAST_IN", "WEST_IN"]},
    ]

    aggregator = SectorAggregator(sectors)
    results = aggregator.aggregate(mock_metrics)

    assert results["NORTH_SOUTH"].aggregated_density == 8  # 5 + 3
    assert results["EAST_WEST"].aggregated_density == 6    # 4 + 2

    print(f"  NORTH_SOUTH: density={results['NORTH_SOUTH'].aggregated_density}")
    print(f"  EAST_WEST: density={results['EAST_WEST'].aggregated_density}")
    print("  [X] PASSED\n")


def test_phase9_graph():
    """Test Phase 9: Graph Construction."""
    print("TEST: Phase 9 - Graph Construction")

    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config", "intersection_config.json",
    )
    with open(config_path) as f:
        config = json.load(f)

    graph = GraphBuilder.from_config(config)
    assert len(graph.nodes) == 3, f"Expected 3 nodes, got {len(graph.nodes)}"
    assert len(graph.edges) == 3, f"Expected 3 edges, got {len(graph.edges)}"

    # Check adjacency
    neighbors = graph.get_neighbors("INT_001")
    assert len(neighbors) == 2, "INT_001 should have 2 neighbors"

    graph_dict = graph.to_dict()
    print(f"  Nodes: {len(graph_dict['nodes'])}, Edges: {len(graph_dict['edges'])}")
    print("  [X] PASSED\n")


def test_phase11_routing():
    """Test Phase 11: Route Engine."""
    print("TEST: Phase 11 - Route Engine")

    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config", "intersection_config.json",
    )
    with open(config_path) as f:
        config = json.load(f)

    graph = GraphBuilder.from_config(config)
    engine = RouteEngine(graph)

    route = engine.find_shortest_path("INT_001", "INT_003")
    assert route is not None, "Should find a route"
    assert route.path[0] == "INT_001"
    assert route.path[-1] == "INT_003"
    assert route.total_distance > 0

    print(f"  Route: {' -> '.join(route.path)}")
    print(f"  Distance: {route.total_distance}m, Time: {route.estimated_time:.1f}s")
    print("  [X] PASSED\n")


def test_end_to_end():
    """Test full pipeline end-to-end."""
    print("TEST: End-to-End Pipeline")
    print("=" * 50)

    pipeline = SynapseSignalPipeline()
    output = pipeline.process_frame(SAMPLE_FRAME_1)

    # Validate output structure
    assert "intersection_id" in output
    assert "timestamp" in output
    assert "lanes" in output
    assert "sectors" in output
    assert "emergency_state" in output
    assert "city_state" in output
    assert "routes" in output

    # Validate intersection_id
    assert output["intersection_id"] == "INT_001"

    # Validate lanes exist
    assert len(output["lanes"]) > 0, "Should have lane data"

    # Validate sectors
    assert len(output["sectors"]) == 2, "Should have 2 sectors"

    # Validate emergency state
    assert output["emergency_state"]["active"] == True, \
        "Emergency should be active (ambulance in frame)"

    # Validate city_state
    assert "nodes" in output["city_state"]
    assert "edges" in output["city_state"]

    print()
    print(f"  intersection_id: {output['intersection_id']}")
    print(f"  lanes: {len(output['lanes'])}")
    print(f"  sectors: {len(output['sectors'])}")
    print(f"  emergency: {output['emergency_state']}")
    print(f"  routes: {len(output['routes'])}")
    print(f"\n  [X] END-TO-END PASSED\n")

    return output


def run_all_tests():
    """Run all tests."""
    print()
    print("+" + "-" * 46 + "+")
    print("|   DEV 2 - PIPELINE TESTS                    |")
    print("+" + "-" * 46 + "+")
    print()

    test_phase1_detection_ingestion()
    test_iou()
    test_phase2_tracker()
    test_phase3_lane_mapper()
    test_phase4_lane_metrics()
    test_phase7_sector_aggregation()
    test_phase9_graph()
    test_phase11_routing()
    output = test_end_to_end()

    print("+" + "-" * 46 + "+")
    print("|   ALL TESTS PASSED [X]                      |")
    print("+" + "-" * 46 + "+")
    print()

    return output


if __name__ == "__main__":
    run_all_tests()
