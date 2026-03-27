"""
Phase 1 — Detection Ingestion
Parses Dev 1 JSON output into structured DetectedObject instances
with added frame_id, timestamp, and centroid computation.
"""

import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class DetectedObject:
    """Single detected vehicle from Dev 1 output."""
    frame_id: int
    timestamp: float
    obj_type: str            # "normal_vehicle" or "emergency_vehicle"
    subtype: str             # "car", "ambulance", "police", "fire_truck", etc.
    bbox: List[int]          # [x1, y1, x2, y2] in pixel coordinates
    confidence: float
    centroid: Tuple[int, int] = (0, 0)
    object_id: Optional[int] = None    # assigned later by tracker
    velocity: float = 0.0              # assigned later by tracker
    lane_id: Optional[str] = None      # assigned later by lane mapper

    def __post_init__(self):
        x1, y1, x2, y2 = self.bbox
        self.centroid = ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def is_emergency(self) -> bool:
        return self.obj_type == "emergency_vehicle"

    @property
    def bbox_area(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)


@dataclass
class FrameData:
    """All detections from a single frame."""
    frame_id: int
    timestamp: float
    normal_count: int
    emergency_count: int
    intersection_id: str = "INT_001"
    objects: List[DetectedObject] = field(default_factory=list)


class DetectionIngestor:
    """
    Parses Dev 1 output JSON and produces structured FrameData.
    
    Supports two Dev 1 output formats:
    1. Full format (with details array containing bboxes)
    2. Summary format (counts only — no details)
    """

    def __init__(self):
        self._frame_counter = 0

    def ingest(self, dev1_json: dict) -> FrameData:
        """Parse a single Dev 1 JSON output into FrameData."""
        frame_id = self._frame_counter
        self._frame_counter += 1

        # Handle both 'timestamp' and 'time_offset' fields
        timestamp = dev1_json.get("timestamp", dev1_json.get("time_offset", 0.0))
        
        # Support both old and new Dev 1 keys
        normal_count = dev1_json.get("normal_count", dev1_json.get("normal_vehicles_count", 0))
        emergency_count = dev1_json.get("emergency_count", dev1_json.get("emergency_vehicles_count", 0))

        objects = []
        # Support both 'details' and 'detections'
        details = dev1_json.get("details", dev1_json.get("detections", []))

        for det in details:
            obj = DetectedObject(
                frame_id=frame_id,
                timestamp=timestamp,
                obj_type=det.get("type", "normal_vehicle"),
                subtype=det.get("subtype", "unknown"),
                bbox=det.get("bbox", [0, 0, 0, 0]),
                confidence=det.get("confidence", 0.0),
            )
            objects.append(obj)

        return FrameData(
            frame_id=frame_id,
            timestamp=timestamp,
            normal_count=normal_count,
            emergency_count=emergency_count,
            intersection_id=dev1_json.get("intersection_id", "INT_001"),
            objects=objects,
        )

    def ingest_from_file(self, filepath: str) -> FrameData:
        """Parse a Dev 1 JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)
        return self.ingest(data)

    def ingest_batch(self, filepaths: List[str]) -> List[FrameData]:
        """Parse multiple Dev 1 JSON files in order."""
        frames = []
        for fp in sorted(filepaths):
            frames.append(self.ingest_from_file(fp))
        return frames

    def reset(self):
        """Reset frame counter."""
        self._frame_counter = 0
