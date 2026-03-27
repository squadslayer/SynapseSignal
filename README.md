# SynapseSignal

AI-based traffic control system using city-wide intersection cameras. Detects emergency vehicles and prioritizes signals based on type (ambulance highest). Uses graph-based routing to create green corridors. Without emergencies, signals adapt dynamically using traffic density and flow imbalance for optimal movement.

## 📖 Project Documentation

For a detailed explanation of the project architecture and data flow, please refer to the **[SYNAPSE_TRUTH.md](SYNAPSE_TRUTH.md)** file.

## 📂 Repository Structure

- **[dev1_pipeline/](dev1_pipeline/)**: Stage 1 - Vehicle Detection
- **[India_Innovates-Dev-2-pipeline-/](India_Innovates-Dev-2-pipeline-/)**: Stage 2 - Traffic Intelligence
- **[synapsesignal/](synapsesignal/)**: Stage 3 - Database & Seeding
- **[Synapse-Signal---Backend-/](Synapse-Signal---Backend-/)**: Stage 4-5 - Backend API & Persistence
- **[input_source/](input_source/)**: Raw input data for the pipeline

## 🚀 Getting Started

1. Set up your environment variables in a `.env` file at the root.
2. Follow the instructions in each sub-directory for specific component setup.
3. Check **[SYNAPSE_TRUTH.md](SYNAPSE_TRUTH.md)** for the complete system flow.
