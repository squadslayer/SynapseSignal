"""
Dev 2 - Main Pipeline Orchestrator
Runs all 12 phases sequentially on Dev 1 JSON output.

Usage:
    # Single frame
    python pipeline.py sample_dev1_output.json
    
    # Multiple frames (batch processing)
    python pipeline.py frame_00000.json frame_00240.json frame_00480.json
    
    # Process all frame_*.json in a directory
    python pipeline.py --dir C:/Users/91964/Downloads
"""

import json
import os
import sys
import glob
from typing import List, Optional

# Pipeline modules
from modules.detection_ingestion import DetectionIngestor, FrameData
from modules.tracker import MultiObjectTracker
from modules.lane_mapper import LaneMapper
from modules.lane_metrics import LaneMetricsComputer
from modules.downstream_estimator import DownstreamEstimator
from modules.flow_features import FlowFeatureComputer
from modules.sector_aggregator import SectorAggregator
from modules.intersection_state import IntersectionStateBuilder
from modules.graph_builder import GraphBuilder
from modules.geo_mapper import GeoMapper
from modules.route_engine import RouteEngine
from output_api import OutputAPI


class SynapseSignalPipeline:
    """
    Dev 2 - Traffic Intelligence Pipeline
    
    Takes Dev 1 detection outputs (JSON per frame sampled every 240 frames)
    and produces flow-aware traffic intelligence for Dev 3.
    
    Pipeline phases:
    1. Detection Ingestion -> parse Dev 1 JSON
    2. Multi-Object Tracking -> assign persistent IDs, compute velocity
    3. Lane Mapping -> assign vehicles to lanes
    4. Lane Metrics -> density, speed, queue per lane
    5. Downstream Estimation -> out_density, capacity
    6. Flow Features -> combined flow-ready inputs
    7. Sector Aggregation -> N-S / E-W grouping
    8. Intersection State -> unified state model
    9. Graph Construction -> city-level graph
    10. Geo-Mapping -> coordinate conversion
    11. Route Engine -> Dijkstra routing
    12. Output API -> Dev 3-ready JSON
    """

    def __init__(self, config_path: str = None):
        """
        Initialize pipeline with intersection configuration.
        
        Args:
            config_path: path to intersection_config.json.
                         Defaults to ./config/intersection_config.json
        """
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "config",
                "intersection_config.json",
            )

        with open(config_path, "r") as f:
            self.config = json.load(f)

        # Extract config values
        self.frame_interval = self.config.get("frame_interval", 240)
        self.fps = self.config.get("fps", 30)
        self.image_width = self.config.get("image_width", 1600)
        self.image_height = self.config.get("image_height", 900)

        # Get first intersection config (primary)
        self.intersection_config = self.config["intersections"][0]
        self.intersection_id = self.intersection_config["intersection_id"]

        # Initialize all modules
        self._init_modules()

    def _init_modules(self):
        """Initialize all pipeline modules."""
        # Phase 1 - Detection Ingestion
        self.ingestor = DetectionIngestor()

        # Phase 2 - Tracker (using supervision ByteTrack)
        self.tracker = MultiObjectTracker(
            track_activation_threshold=0.05,  # low threshold for 240-frame gaps
            lost_track_buffer=30,
        )

        # Phase 3 - Lane Mapper
        self.lane_mapper = LaneMapper(self.intersection_config["lanes"])

        # Phase 4 - Lane Metrics
        self.metrics_computer = LaneMetricsComputer(stopped_speed_threshold=5.0)

        # Phase 5 - Downstream Estimator
        self.downstream_estimator = DownstreamEstimator(
            self.intersection_config["lanes"]
        )

        # Phase 6 - Flow Features
        self.flow_computer = FlowFeatureComputer()

        # Phase 7 - Sector Aggregator
        self.sector_aggregator = SectorAggregator(
            self.intersection_config["sectors"]
        )

        # Phase 8 - Intersection State Builder
        self.state_builder = IntersectionStateBuilder(self.intersection_id)

        # Phase 9 - City Graph
        self.city_graph = GraphBuilder.from_config(self.config)

        # Phase 10 - Geo Mapper
        self.geo_mapper = GeoMapper(
            self.config.get("all_intersections_geo", {}),
            (self.image_width, self.image_height),
        )

        # Phase 11 - Route Engine
        self.route_engine = RouteEngine(self.city_graph)

    def process_frame(self, dev1_json: dict) -> dict:
        """
        Process a single Dev 1 output frame through the full pipeline.
        
        Args:
            dev1_json: parsed Dev 1 JSON output dict
        
        Returns:
            Complete Dev 3-ready output dict
        """
        # --- Phase 1: Detection Ingestion ---
        frame_data = self.ingestor.ingest(dev1_json)
        print(f"  Phase 1: Ingested {len(frame_data.objects)} objects "
              f"(normal={frame_data.normal_count}, emergency={frame_data.emergency_count})")

        # --- Phase 2: Multi-Object Tracking ---
        active_tracks = self.tracker.update(frame_data)
        print(f"  Phase 2: Tracking {len(active_tracks)} active tracks")

        # --- Phase 3: Lane Mapping ---
        # Map tracked detections to lanes
        lane_assignments = self.lane_mapper.map_frame(frame_data.objects)
        assigned_count = sum(len(v) for v in lane_assignments.values())
        print(f"  Phase 3: Assigned {assigned_count}/{len(frame_data.objects)} "
              f"objects to lanes")

        # --- Phase 4: Lane Metrics ---
        lane_metrics = self.metrics_computer.compute(lane_assignments)
        for lid, m in lane_metrics.items():
            if m.in_density > 0:
                print(f"  Phase 4: {lid} -> density={m.in_density}, "
                      f"speed={m.avg_speed:.1f}, queue={m.queue_length}")

        # --- Phase 5: Downstream Estimation ---
        downstream_states = self.downstream_estimator.estimate(lane_metrics)
        for lid, ds in downstream_states.items():
            print(f"  Phase 5: {lid} -> out_density={ds.out_density}, "
                  f"capacity={ds.capacity}")

        # --- Phase 6: Flow Features ---
        flow_features = self.flow_computer.compute(lane_metrics, downstream_states)
        print(f"  Phase 6: Computed flow features for {len(flow_features)} lanes")

        # --- Phase 7: Sector Aggregation ---
        sector_states = self.sector_aggregator.aggregate(lane_metrics)
        for sid, s in sector_states.items():
            print(f"  Phase 7: {sid} -> density={s.aggregated_density}, "
                  f"speed={s.avg_speed:.1f}")

        # --- Phase 8: Intersection State ---
        intersection_state = self.state_builder.build(
            timestamp=frame_data.timestamp,
            flow_features=flow_features,
            sector_states=sector_states,
            lane_metrics=lane_metrics,
            active_tracks=active_tracks,
            lane_assignments=lane_assignments,
        )
        # Use dynamic intersection_id from Dev 1 feed
        intersection_id = frame_data.intersection_id
        state_dict = intersection_state.to_dict()
        state_dict["intersection_id"] = intersection_id
        
        print(f"  Phase 8: Built intersection state for {intersection_id} "
              f"(emergency={state_dict['emergency_state']['active']})")

        # --- Phase 9: Graph Construction & Edge Updates ---
        # Update edges connected to this intersection based on current flow
        for neighbor, edge in self.city_graph.get_neighbors(intersection_id):
            # Update edge metrics: total vehicle count on the connected road
            total_road_vehicles = sum(m.in_density for m in lane_metrics.values())
            avg_road_speed = sum(m.avg_speed for m in lane_metrics.values()) / len(lane_metrics)
            self.city_graph.update_edge_metrics(edge.edge_id, total_road_vehicles, avg_road_speed)

        self.city_graph.attach_intersection_state(
            intersection_id, state_dict
        )
        graph_dict = self.city_graph.to_dict()
        print(f"  Phase 9: Updated graph with real-time metrics for {intersection_id}")

        # --- Phase 10: City-Level State Aggregation ---
        # In a real city, this would aggregate from multiple pipeline instances.
        # For now, we normalize the current graph state.
        city_metrics = {
            "total_vehicles": sum(e.vehicle_count for e in self.city_graph.edges),
            "global_congestion": sum(1 for e in self.city_graph.edges if e.congestion_level != "low") / len(self.city_graph.edges) if self.city_graph.edges else 0
        }
        print(f"  Phase 10: Aggregated city state (global_congestion={city_metrics['global_congestion']:.2f})")
        emergency_geo = None
        if state_dict["emergency_state"]["active"]:
            for ev in state_dict["emergency_state"]["vehicles"]:
                cx, cy = ev["centroid"]
                lat, lon = self.geo_mapper.pixel_to_geo(cx, cy)
                emergency_geo = {"lat": lat, "lon": lon, "velocity": ev["velocity"]}
                print(f"  Phase 10: Emergency vehicle at ({lat}, {lon})")

        # --- Phase 11: Route Engine ---
        routes_data = []
        if state_dict["emergency_state"]["active"]:
            # Find routes from current intersection to all others
            for node_id in self.city_graph.nodes:
                if node_id != intersection_id:
                    routes = self.route_engine.find_routes(
                        intersection_id, node_id
                    )
                    for route in routes:
                        routes_data.append(route.to_dict())
                        print(f"  Phase 11: Route {route.route_id} -> "
                              f"dist={route.total_distance}, "
                              f"time={route.estimated_time:.1f}s")

        # --- Phase 12: Output API ---
        output = OutputAPI.format_output(
            intersection_state=state_dict,
            city_graph=graph_dict,
            routes=routes_data,
            emergency_geo=emergency_geo,
        )

        return output

    def process_batch(self, dev1_files: List[str]) -> List[dict]:
        """
        Process multiple Dev 1 frame files in sequence.
        
        Args:
            dev1_files: list of JSON file paths (will be sorted by name)
        
        Returns:
            List of Dev 3-ready output dicts, one per frame
        """
        results = []
        sorted_files = sorted(dev1_files)

        for i, filepath in enumerate(sorted_files):
            print(f"\n{'='*60}")
            print(f"FRAME {i} - {os.path.basename(filepath)}")
            print(f"{'='*60}")

            with open(filepath, "r") as f:
                dev1_json = json.load(f)

            output = self.process_frame(dev1_json)
            results.append(output)

        return results

    def reset(self):
        """Reset all stateful modules."""
        self.ingestor.reset()
        self.tracker.reset()


def main():
    """CLI entry point."""
    pipeline = SynapseSignalPipeline()

    if len(sys.argv) < 2:
        # Default: run with sample data
        sample_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "sample_dev1_output.json",
        )
        if os.path.exists(sample_path):
            print("Running with sample Dev 1 output...")
            print()
            with open(sample_path, "r") as f:
                dev1_json = json.load(f)
            output = pipeline.process_frame(dev1_json)
            print(f"\n{'='*60}")
            print("DEV 2 OUTPUT (for Dev 3)")
            print(f"{'='*60}")
            print(OutputAPI.to_json(output))

            # Save output
            out_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "dev2_output.json",
            )
            OutputAPI.save_to_file(output, out_path)
            print(f"\nOutput saved to: {out_path}")
        else:
            print("No input files provided and no sample data found.")
            print("Usage: python pipeline.py <frame.json> [frame2.json ...]")
            print("       python pipeline.py --dir <directory>")
            sys.exit(1)

    elif sys.argv[1] == "--dir":
        # Process all frame_*.json in a directory
        directory = sys.argv[2] if len(sys.argv) > 2 else "."
        pattern = os.path.join(directory, "frame_*.json")
        files = glob.glob(pattern)
        if not files:
            print(f"No frame_*.json files found in {directory}")
            sys.exit(1)

        print(f"Found {len(files)} frame files in {directory}")
        results = pipeline.process_batch(files)

        # Save batch output
        out_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "dev2_batch_output.json",
        )
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nBatch output saved to: {out_path}")

    else:
        # Process specified files
        files = sys.argv[1:]
        if len(files) == 1:
            with open(files[0], "r") as f:
                dev1_json = json.load(f)
            output = pipeline.process_frame(dev1_json)
            print(f"\n{'='*60}")
            print("DEV 2 OUTPUT (for Dev 3)")
            print(f"{'='*60}")
            print(OutputAPI.to_json(output))
        else:
            results = pipeline.process_batch(files)
            out_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "dev2_batch_output.json",
            )
            with open(out_path, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\nBatch output saved to: {out_path}")


if __name__ == "__main__":
    main()
