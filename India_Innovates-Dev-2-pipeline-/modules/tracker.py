"""
Phase 2 — Multi-Object Tracker (using supervision ByteTrack)
Assigns persistent object IDs across frames using the real ByteTrack algorithm.
Computes velocity from centroid displacement between frames.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import numpy as np
import supervision as sv


@dataclass
class Track:
    """A tracked object across multiple frames."""
    track_id: int
    bbox: List[int]                          # current [x1, y1, x2, y2]
    centroid: Tuple[int, int]                # current centroid
    obj_type: str
    subtype: str
    confidence: float
    velocity: float = 0.0                    # pixels per second
    trajectory: List[Tuple[int, int]] = field(default_factory=list)
    age: int = 0                             # frames since creation
    frames_since_seen: int = 0               # frames since last matched
    last_timestamp: float = 0.0

    @property
    def is_emergency(self) -> bool:
        return self.obj_type == "emergency_vehicle"


class MultiObjectTracker:
    """
    Multi-object tracker using the real ByteTrack algorithm from `supervision`.
    
    - Matches new detections to existing tracks
    - Handles low-confidence detections (two-stage matching)
    - Assigns persistent track IDs
    - Computes velocity from centroid displacement
    """

    def __init__(self, track_activation_threshold: float = 0.25, lost_track_buffer: int = 30, minimum_matching_threshold: float = 0.8, frame_rate: int = 30):
        # We store parameters to allow resetting
        self.track_activation_threshold = track_activation_threshold
        self.lost_track_buffer = lost_track_buffer
        self.minimum_matching_threshold = minimum_matching_threshold
        self.frame_rate = frame_rate
        
        # Initialize supervision ByteTrack adapter
        self.byte_tracker = sv.ByteTrack(
            track_activation_threshold=track_activation_threshold,
            lost_track_buffer=lost_track_buffer,
            minimum_matching_threshold=minimum_matching_threshold,
            frame_rate=frame_rate
        )
        self.active_tracks: Dict[int, Track] = {}

    def update(self, frame_data) -> List[Track]:
        """
        Update tracker with new frame detections.
        
        Args:
            frame_data: FrameData object from DetectionIngestor
            
        Returns:
            List of currently active Track objects
        """
        detections_list = frame_data.objects
        timestamp = frame_data.timestamp

        if len(detections_list) == 0:
            # No detections, tracker updates internally and we return empty for current frame 
            # (ByteTrack doesn't require empty updates explicitly via update_with_detections for our simple wrap, 
            # but if we wanted full lost track maintenance we'd step it).
            # For our pipeline, we just return empty.
            return []

        # Prepare supervision detections
        xyxy = []
        confidence = []
        class_id = []
        det_map = {}  # Map to get back original object via class_id

        for i, det in enumerate(detections_list):
            xyxy.append(det.bbox)
            confidence.append(det.confidence)
            class_id.append(i)  # Use index as class_id to map back easily
            det_map[i] = det

        # Create supervision Detections object
        sv_detections = sv.Detections(
            xyxy=np.array(xyxy, dtype=np.float32),
            confidence=np.array(confidence, dtype=np.float32),
            class_id=np.array(class_id, dtype=int)
        )

        try:
            # Run ByteTrack
            tracked_detections = self.byte_tracker.update_with_detections(sv_detections)
        except Exception as e:
            print(f"ByteTrack update failed: {e}")
            return list(self.active_tracks.values())

        new_active_tracks = {}

        # tracked_detections contains only the matched active tracks for this frame
        for i in range(len(tracked_detections)):
            t_id = tracked_detections.tracker_id[i]
            
            # Retrieve original detection using class_id mapping
            orig_idx = tracked_detections.class_id[i]
            orig_det = det_map[orig_idx]

            # Supervision returns float boxes, convert to int list
            bbox = [int(v) for v in tracked_detections.xyxy[i].tolist()]
            new_cx, new_cy = orig_det.centroid

            if t_id in self.active_tracks:
                # Update existing track
                track = self.active_tracks[t_id]
                old_cx, old_cy = track.centroid
                
                # Compute velocity
                dt = timestamp - track.last_timestamp
                # Avoid division by zero, and since we have 8 sec offset, we track velocity if dt > 0
                if dt > 0:
                    displacement = ((new_cx - old_cx) ** 2 + (new_cy - old_cy) ** 2) ** 0.5
                    track.velocity = displacement / dt
                else:
                    track.velocity = 0.0

                # Update track attributes
                track.bbox = bbox
                track.centroid = orig_det.centroid
                track.obj_type = orig_det.obj_type
                track.subtype = orig_det.subtype
                track.confidence = orig_det.confidence
                track.trajectory.append(orig_det.centroid)
                track.age += 1
                track.frames_since_seen = 0
                track.last_timestamp = timestamp

                new_active_tracks[t_id] = track
            else:
                # Create brand new track
                track = Track(
                    track_id=t_id,
                    bbox=bbox,
                    centroid=orig_det.centroid,
                    obj_type=orig_det.obj_type,
                    subtype=orig_det.subtype,
                    confidence=orig_det.confidence,
                    velocity=0.0,
                    trajectory=[orig_det.centroid],
                    age=0,
                    frames_since_seen=0,
                    last_timestamp=timestamp,
                )
                new_active_tracks[t_id] = track

            # Link the tracker ID and computed velocity back to the original detection object
            orig_det.object_id = t_id
            orig_det.velocity = track.velocity

        self.active_tracks = new_active_tracks
        return list(self.active_tracks.values())

    def reset(self):
        """Reset tracker state."""
        self.byte_tracker = sv.ByteTrack(
            track_activation_threshold=self.track_activation_threshold,
            lost_track_buffer=self.lost_track_buffer,
            minimum_matching_threshold=self.minimum_matching_threshold,
            frame_rate=self.frame_rate
        )
        self.active_tracks = {}

    def get_track_by_id(self, track_id: int) -> Optional[Track]:
        """Get a track by its ID."""
        return self.active_tracks.get(track_id)

def compute_iou(box_a: List[int], box_b: List[int]) -> float:
    """Compute Intersection over Union between two bboxes [x1,y1,x2,y2]."""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    inter_area = max(0, x2 - x1) * max(0, y2 - y1)
    if inter_area == 0:
        return 0.0

    area_a = max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1])
    area_b = max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1])

    union_area = area_a + area_b - inter_area
    if union_area == 0:
        return 0.0

    return inter_area / union_area
