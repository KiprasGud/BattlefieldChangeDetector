# Žvalgas AI — Aerial Reconnaissance & Battlefield Change Detection System

## System Overview

**Žvalgas AI** is a mission-critical ISR (Intelligence, Surveillance, Reconnaissance) operator terminal designed for edge-computing environments. It accelerates rapid change detection and enables ATAK sensor fusion integration by autonomously comparing past and present aerial reconnaissance imagery to detect targets, structural changes, and terrain modifications.

Built strictly in accordance with the `UI.md` design system, the architecture enforces a brutalist, zero-decoration philosophy: absolute grids, `border-radius: 0`, and 0ms transitions to prioritize information density and instantaneous operator feedback.

---

## System Architecture (The 3-Pane Operator Terminal)

The terminal operates within a high-density, rigid CSS Grid (`25/55/20`), divided into three specialized panes:

### 1. Left Sidebar (Ingestion & Parameters - 25%)
- **Dual Ingestion Dropzones**: Direct file mounts for Baseline (Past) and Recon (Present) imagery.
- **Target Criteria Toggles**: Multi-selection capability for dynamic target parsing (`VEHICLES`, `CRATERS`, `TRENCHES / TREES`, `STRUCTURES`), combined with ad-hoc custom string queries.
- **Execution Controls**: Keyboard-first execution bound to `[F5]` or `[CTRL+ENTER]`.

### 2. Center Stage (Diff Engine - 55%)
- **Interactive Image Slider**: A zero-latency wipe tool for real-time visual alignment between baseline and recon layers.
- **Dynamic Vector HUD**: Bounding box overlays generated dynamically from the backend pipeline, featuring attached monospaced data tags (e.g., `[TRGT-01]`, `[TRGT-02]`).
- **Heatmap Density Overlay**: For rapid triage of highly-altered sectors.
- **Hardware-Accelerated Rendering**: Drag tracking decoupled via the `requestAnimationFrame` API to guarantee 60 FPS slider scrubbing on low-power edge devices.

### 3. Right Sidebar (Telemetry & Output - 20%)
- **Live UTC Telemetry**: Timestamped system log stream capturing ingestions, processing stages, and warnings.
- **Coordinate Readouts**: Bounding coordinates `[0-1000]` mapped to the image plane and derived geolocation metadata.
- **CoT XML Payload Serializer**: Real-time Cursor on Target (CoT) XML serialization & inline inspection panel for direct ATAK system synchronization. Supports JSON exports.

---

## Design System & Keybindings (`UI.md` Standards)

The terminal rejects standard SaaS aesthetics in favor of a utilitarian, Bloomberg-terminal-style approach.

- **Monochromatic Palette**: Strict 1px grid borders segregating terminal partitions. No drop shadows.
- **Dual Typography**: Monospaced fonts (JetBrains Mono / Fira Code) for telemetry, coordinates, and tags. Geometric sans-serif (Inter) for structural labels.
- **Tactical Display Toggles (Lighting Adaptability)**:
  - `[ALT+N]` — **Night Vision Mode**: Monochromatic green text (`#16A34A`) on absolute black (`#000000`).
  - `[ALT+S]` — **Sun/Daylight Mode**: Stark high-contrast black text on blinding white background for glare resistance.
- **Buffer Purge Mechanism**:
  - `[ESC]` — Arms the purge sequence.
  - `[ESC]` (Double-tap within 1000ms) — Safely destroys image buffers and clears tracking data without breaking layout geometry or using browser popup confirms.

---

## Technical Stack & Pipeline Workflow

### Frontend
- **Framework**: React (TypeScript) powered by Vite.
- **Layout**: Native CSS Grid Architecture.
- **Graphics**: Canvas API & standard DOM overlays managed via `requestAnimationFrame`.

### Backend & Processing
- **Engine**: Python / FastAPI.
- **Vision Processing**: OpenCV for image registration, multi-point alignment, and structural warping.
- **AI Core**: Gemini 2.5 API pipeline utilized for high-fidelity change detection, structural comparison, and target classification.

### Data Schema
- **Exports**: Extensible to Cursor on Target (CoT) XML (MIL-STD compatible) and strict JSON payload formatting, resolving targets dynamically based on ingested criteria (e.g., `a-h-G-U-C` for hostile vehicles).

---

## Local Setup & Development

### Prerequisites
- Node.js (v18+)
- npm or yarn
- Python 3.10+ (for backend API server)
- Gemini API Key

### Installation

1. **Clone the Repository**
   ```bash
   git clone <repository_url>
   cd BattlefieldChangeDetector
   ```

2. **Backend Setup**
   Ensure your Python environment is active and dependencies are installed.
   ```bash
   cd backend
   pip install -r requirements.txt
   ```
   Set up your `.env` file with your Gemini API credentials:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```
   Start the backend server (FastAPI):
   ```bash
   uvicorn main:app --reload
   ```

3. **Frontend Setup**
   Open a new terminal session and navigate to the frontend directory:
   ```bash
   cd frontend
   npm install
   ```

4. **Launch the Operator Terminal**
   Start the Vite development server:
   ```bash
   npm run dev
   ```
   *The terminal is now accessible locally. Default upstream routing dynamically handles `/api/*` proxies to the backend.*

5. **Build for Production Edge Deployment**
   ```bash
   npm run build
   ```
