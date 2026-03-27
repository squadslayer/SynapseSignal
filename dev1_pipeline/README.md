# SynapseSignal — Dev 1: Vehicle Detection & Classification Pipeline

## Overview

Dev 1 is the **foundation layer** of SynapseSignal. It relies on a two-stage YOLO pipeline to robustly detect and classify vehicles.

```
Frame → YOLO Model 1 (emergency / non_emergency)
      → non_emergency  → pass-through
      → emergency      → crop → YOLO Model 2 → subtype (ambulance / fire / police)
      → Merged structured JSON output
```

## Files

| File | Purpose |
|------|---------|
| `dev1_pipeline.py` | Core engine — all pipeline logic |
| `dev1_notebook.ipynb` | Interactive notebook for running & testing |
| `requirements.txt` | All dependencies |
| `models/yolo_detector.pt` | Stage 1 YOLO weights |
| `models/emergency_classifier.pt` | Stage 2 YOLO weights |

## Output Format (Per Frame)

```json
[
  {
    "type": "normal_vehicle",
    "bbox": [x1, y1, x2, y2],
    "confidence": 0.88
  },
  {
    "type": "emergency_vehicle",
    "subtype": "ambulance",
    "subtype_confidence": 0.91,
    "bbox": [x1, y1, x2, y2],
    "confidence": 0.94
  }
]
```

## Quickstart

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run on image (CLI)
```bash
python dev1_pipeline.py --source "..\Dev1 pipeline\indian traffic image.jpg"
```

### 3. Run on video (CLI)
```bash
python dev1_pipeline.py --source "..\Dev1 pipeline\153283-804933523_medium.mp4" --max-frames 200
```

### 4. Interactive Testing
Open `dev1_notebook.ipynb` and run the cells.

## Dev 2 Integration API

```python
from dev1_pipeline import get_dev2_payload
payload = get_dev2_payload(frame, yolo_model, classifier, cls_device)
# Returns: {"normal_vehicles": [...], "emergency_vehicles": [...]}
```
