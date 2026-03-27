"""
SynapseSignal — Dev 1 Detection & Classification Pipeline (Gemini Fallback)
===========================================================================
Pipeline:
    Frame → Gemini 2.5 Flash API (Zero-Shot Object Detection)
         → Structured JSON response decoding
            ├── Normal Vehicles      → pass-through
            └── Emergency Vehicles   → specify subtype
         → Merge → Structured JSON output per frame

Outputs per frame:
    [
        {"type": "normal_vehicle",   "bbox": [...], "confidence": float},
        {"type": "emergency_vehicle","subtype": "ambulance", "confidence": float},
    ]
"""

import os
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

import cv2
import numpy as np
import supervision as sv
from dotenv import load_dotenv
import redis

# Google GenAI imports
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dev1")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables. Please check your .env file.")

# Define the precise JSON schema we want Gemini to return
detection_schema = {
    "type": "OBJECT",
    "properties": {
        "vehicles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "vehicle_type": {
                        "type": "STRING",
                        "description": "Must be exactly 'normal_vehicle' or 'emergency_vehicle'"
                    },
                    "subtype": {
                        "type": "STRING",
                        "description": "If emergency_vehicle, must be 'ambulance', 'fire_truck', or 'police'. If normal_vehicle, use 'none'."
                    },
                    "bbox_2d": {
                        "type": "ARRAY",
                        "items": {"type": "INTEGER"},
                        "description": "Bounding box [ymin, xmin, ymax, xmax] coordinates normalized from 0 to 1000. E.g., [100, 200, 300, 400] means ymin=0.1, xmin=0.2, etc. (ymin is top, xmin is left, ymax is bottom, xmax is right)."
                    }
                },
                "required": ["vehicle_type", "subtype", "bbox_2d"]
            }
        }
    },
    "required": ["vehicles"]
}

def build_model(api_key: str = GEMINI_API_KEY):
    """Initialize the Google GenAI Cloud Client."""
    log.info("Connecting to Gemini Vision API (gemini-2.5-flash)")
    return genai.Client(api_key=api_key)

# ─────────────────────────────────────────────────────────────────────────────
# CORE PROCESSING
# ─────────────────────────────────────────────────────────────────────────────
# Global tracker to ensure we never exceed Gemini's 15 Requests Per Minute (RPM) free tier
LAST_API_CALL_TIME = 0.0
MIN_SECONDS_BETWEEN_CALLS = 4.1  # 60s / 15 requests = 4s. Extra 0.1s for safety.

def process_frame(
    frame: np.ndarray,
    client: Any,
) -> Tuple[List[Dict[str, Any]], sv.Detections, List[str]]:
    """
    Run the Dev 1 pipeline using Gemini Vision API.
    Returns:
        1. List of JSON dicts for downstream Dev 2
        2. sv.Detections object for Supervision
        3. Raw label strings for annotation
    """
    if frame is None or frame.size == 0:
        return [], sv.Detections.empty(), []

    # Convert cv2 frame (BGR) to PIL Image (RGB) for Gemini
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    h, w = frame.shape[:2]

    # Enforce Rate Limiting (Throttle)
    global LAST_API_CALL_TIME
    time_since_last_call = time.time() - LAST_API_CALL_TIME
    if time_since_last_call < MIN_SECONDS_BETWEEN_CALLS:
        sleep_time = MIN_SECONDS_BETWEEN_CALLS - time_since_last_call
        log.info(f"Rate limiter active: Throttling request for {sleep_time:.2f} seconds to avoid billing...")
        time.sleep(sleep_time)

    # Call Gemini API
    log.info("Sending frame to Gemini...")
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                "Analyze this traffic image. CRITICAL OBJECTIVE: You MUST search for and distinctly bound any emergency vehicles (ambulance, fire_truck, police car) present. Put emergency vehicles first in your output list. Then, detect the other normal vehicles around it. For each vehicle, provide its bounding box and classify it.",
                pil_img
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=detection_schema,
                temperature=0.1,
            ),
        )
        LAST_API_CALL_TIME = time.time()
        result = json.loads(response.text)
    except Exception as e:
        log.error(f"Gemini API Error: {e}")
        return [], sv.Detections.empty(), []

    vehicles = result.get("vehicles", [])
    
    if not vehicles:
        return [], sv.Detections(xyxy=np.empty((0, 4)), class_id=np.empty((0,))), []

    xyxy = []
    class_ids = []
    confidences = []
    labels = []
    
    output = []
    
    for idx, v in enumerate(vehicles):
        v_type = v.get("vehicle_type", "normal_vehicle")
        subtype = v.get("subtype", "none")
        bbox_1000 = v.get("bbox_2d", [0, 0, 0, 0])
        
        if len(bbox_1000) != 4:
            continue
            
        ymin, xmin, ymax, xmax = [val / 1000.0 for val in bbox_1000]
        y1, x1, y2, x2 = int(ymin * h), int(xmin * w), int(ymax * h), int(xmax * w)
        
        xyxy.append([x1, y1, x2, y2])
        class_ids.append(idx)
        # Gemini doesn't output traditional "confidence", we just hardcode 0.99 for display
        confidences.append(0.99)
        
        is_emergency = (v_type == "emergency_vehicle")
        
        if is_emergency:
            labels.append(subtype)
            output.append({
                "type":               "emergency_vehicle",
                "subtype":            subtype,
                "subtype_confidence": 0.99,
                "bbox":               [x1, y1, x2, y2],
                "confidence":         0.99,
            })
        else:
            labels.append("vehicle")
            output.append({
                "type":       "normal_vehicle",
                "bbox":       [x1, y1, x2, y2],
                "confidence": 0.99,
            })
            
    if not xyxy:
        return [], sv.Detections(xyxy=np.empty((0, 4)), class_id=np.empty((0,))), []
        
    detections = sv.Detections(
        xyxy=np.array(xyxy),
        confidence=np.array(confidences),
        class_id=np.array(class_ids)
    )

    return output, detections, labels

# ─────────────────────────────────────────────────────────────────────────────
# ANNOTATION
# ─────────────────────────────────────────────────────────────────────────────
box_annotator   = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()

def annotate_frame(frame: np.ndarray, detections: sv.Detections, labels: List[str]) -> np.ndarray:
    """Draw bounding boxes and labels using Supervision."""
    annotated = frame.copy()
    if len(detections) > 0:
        annotated = box_annotator.annotate(scene=annotated, detections=detections)
        annotated = label_annotator.annotate(scene=annotated, detections=detections, labels=labels)
    return annotated

# ─────────────────────────────────────────────────────────────────────────────
# RUNNERS
# ─────────────────────────────────────────────────────────────────────────────
def run_on_image(image_path: str, client: Any, output_dir: str = "dev1_output"):
    """Run pipeline on a single image and save result."""
    if str(image_path).lower().endswith(".avif"):
        import pillow_avif
        from PIL import Image
        try:
            pil_img = Image.open(image_path).convert('RGB')
            frame = np.array(pil_img)[:, :, ::-1].copy()
        except Exception as e:
            log.error(f"Cannot read AVIF image: {e}")
            return []
    else:
        frame = cv2.imread(image_path)
        
    if frame is None:
        log.error(f"Cannot read image: {image_path}")
        return []

    output, dets, labels = process_frame(frame, client)

    os.makedirs(output_dir, exist_ok=True)
    vis = annotate_frame(frame, dets, labels)
    out_path = os.path.join(output_dir, "annotated_" + Path(image_path).stem + ".jpg")
    cv2.imwrite(out_path, vis)
    # Save Dev 2 JSON Feed
    dev2_data = {
        "intersection_id": os.getenv("INTERSECTION_ID", "INT_001"),
        "timestamp": time.time(),
        "source": str(image_path),
        "normal_vehicles_count": len([d for d in output if d["type"] == "normal_vehicle"]),
        "emergency_vehicles_count": len([d for d in output if d["type"] == "emergency_vehicle"]),
        "detections": output
    }
    with open(os.path.join(output_dir, "dev2_feed.json"), "w") as f:
        json.dump(dev2_data, f, indent=2)
    
    # NEW: Push to Redis for real-time bridge
    try:
        r = redis.Redis(host=os.getenv("SYNAPSE_REDIS_HOST", "localhost"), 
                        port=int(os.getenv("SYNAPSE_REDIS_PORT", 6379)), 
                        db=0)
        r.publish("synapse:frames", json.dumps(dev2_data))
        log.info("Published frame to Redis channel 'synapse:frames'")
    except Exception as e:
        log.warning(f"Failed to publish to Redis: {e}")

    log.info(f"Dev 2 JSON feed updated: {len(output)} total vehicles.")
    
    return output

def process_video(video_path: str, client: Any, output_dir: str = "dev1_output", frame_interval_seconds: float = 5.0):
    """
    Process a video file by sampling frames at specific time intervals.
    Example: 1 frame every 5 seconds.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log.error(f"Cannot open video: {video_path}")
        return []
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_step = int(fps * frame_interval_seconds)
    
    log.info(f"Processing video: {video_path} ({total_frames} frames, {fps:.1f} FPS)")
    log.info(f"Sampling every {frame_step} frames (~{frame_interval_seconds} seconds)")
    
    os.makedirs(output_dir, exist_ok=True)
    video_results = []
    
    count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        if count % frame_step == 0:
            timestamp = count / fps
            log.info(f"--- Processing Frame at {timestamp:.1f}s ---")
            
            output, dets, labels = process_frame(frame, client)
            
            # Save visual
            vis = annotate_frame(frame, dets, labels)
            frame_filename = f"frame_{timestamp:04.1f}s.jpg"
            out_path = os.path.join(output_dir, frame_filename)
            cv2.imwrite(out_path, vis)
            
            # Update Dev 2 Feed for this frame
            dev2_data = {
                "intersection_id": os.getenv("INTERSECTION_ID", "INT_001"),
                "timestamp": timestamp,
                "normal_vehicles_count": len([d for d in output if d["type"] == "normal_vehicle"]),
                "emergency_vehicles_count": len([d for d in output if d["type"] == "emergency_vehicle"]),
                "detections": output
            }
            with open(os.path.join(output_dir, f"dev2_frame_{timestamp:04.1f}s.json"), "w") as f:
                json.dump(dev2_data, f, indent=2)
            
            # NEW: Push to Redis for real-time bridge
            try:
                r = redis.Redis(host=os.getenv("SYNAPSE_REDIS_HOST", "localhost"), 
                                port=int(os.getenv("SYNAPSE_REDIS_PORT", 6379)), 
                                db=0)
                r.publish("synapse:frames", json.dumps(dev2_data))
                log.info(f"Published video frame {timestamp:.1f}s to Redis")
            except Exception as e:
                log.warning(f"Failed to publish to Redis: {e}")
            
            video_results.append(dev2_data)
            
        count += 1
        
    cap.release()
    log.info(f"Video processing complete. Results for {len(video_results)} frames.")
    return video_results

def get_dev2_payload(frame: np.ndarray, client: Any) -> Dict[str, Any]:
    """Public API for Dev 2 (congestion tracker)."""
    detections, _, _ = process_frame(frame, client)
    return {
        "normal_vehicles":    [d for d in detections if d["type"] == "normal_vehicle"],
        "emergency_vehicles": [d for d in detections if d["type"] == "emergency_vehicle"],
    }

if __name__ == "__main__":
    import sys
    client = build_model()
    
    # Check for CLI argument
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
    else:
        # Check for common default paths
        possible_defaults = [
            r"img with emergency.avif",
            r"..\Dev1 pipeline\img with emergency.avif",
            r"..\input_source\sample.jpg"
        ]
        input_path = next((p for p in possible_defaults if os.path.exists(p)), None)

    if input_path and os.path.exists(input_path):
        if input_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
            process_video(input_path, client)
        else:
            result = run_on_image(input_path, client)
            print(f"✅ Processed {input_path}")
            print(json.dumps(result[:2], indent=2))
    else:
        print(f"❌ No input file found. Usage: python dev1_pipeline.py <image_or_video_path>")
        print(f"Searching in: {os.getcwd()}")
