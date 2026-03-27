# SynapseSignal: The Complete Truth

A real-time, city-scale traffic intelligence and management system for Delhi.

## 🏗️ Architecture Overview

The project is structured as a phased pipeline (Dev 1 through Dev 5), moving from raw data to actionable intelligence.

### 🎥 Stage 1: Vehicle Detection (Dev 1)
- **Input:** Raw video/images from `input_source/`.
- **Logic:** YOLO-based detection or Gemini Vision API processing.
- **Output:** Frame-by-frame vehicle telemetry (classification, bounding boxes).
- **Primary Folder:** `dev1_pipeline/`

### 🗺️ Stage 2: Traffic Intelligence (Dev 2)
- **Logic:** Maps the 2D detections onto a real-world city graph (Delhi graph).
- **Metric Calculation:** Counts vehicles per lane, calculates flow density, and detects congestion points.
- **Primary Folder:** `India_Innovates-Dev-2-pipeline-`

### 📊 Stage 3: Database & Seeding (Dev 3)
- **Database:** PostgreSQL.
- **Function:** Stores the "City Graph" (nodes/edges) and historical traffic metrics.
- **Seeding:** Uses OSMnx to scrape Delhi's road network and populate the graph.
- **Primary Folder:** `synapsesignal/` (specifically `database/` and `scripts/`)

### ⚙️ Stage 4-5: Backend Control (Dev 4/5)
- **Framework:** Python / FastAPI.
- **Function:** Real-time persistence and API layer for dashboards.
- **Primary Folder:** `Synapse-Signal---Backend-`

---

## 🚀 How It All Works Together
1. **Source:** Videos/images are placed in `input_source/`.
2. **Detect:** `dev1_pipeline/` processes the source and generates telemetry.
3. **Map:** `India_Innovates-Dev-2-pipeline-` interprets telemetry against the city graph.
4. **Persist:** The `Synapse-Signal---Backend-` (Backend) saves this data to the database (PostgreSQL) defined in `synapsesignal`.
5. **Serve:** The Backend API serves this data to a frontend.

## 🛠️ Maintenance & Cleanup
- Output JSONs in Dev 2 are automatically ignored by `.gitignore`.
- Environment variables ([.env](.env)) must contain PostgreSQL credentials and API keys.
