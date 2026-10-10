# UI.md - Tactical Operator Terminal Design System

This document is the absolute source of truth for the operator terminal UI. 

## 1. Core Philosophy
- **Mission Critical:** The interface is built for high-pressure environments (ISR data processing).
- **Utilitarian & Structural:** Zero decoration. No gradients, no shadows, no rounded corners (`border-radius: 0`), and no floating elements.
- **Information Density:** Pad elements tightly. Do not waste screen real estate on empty whitespace. The UI should look like a Bloomberg terminal or aviation software.

## 2. Color Palette (Monochromatic & High Contrast)
- **Backgrounds:** Deep charcoal (`#111827`) for dark mode (default) or flat concrete gray (`#E5E7EB`) for light mode.
- **Borders:** Crisp, 1px solid high-contrast lines (`#374151` in dark mode, `#9CA3AF` in light mode) to separate the three panes.
- **Accents:** Monochromatic and functional. Use a highly visible warning/attention color only when strictly necessary (e.g., `#EF4444` for errors, `#10B981` for successful alignment). 
- **Text:** High contrast white/off-white (`#F9FAFB`) in dark mode, or absolute black (`#000000`) in light mode.

## 3. Typography
- **Data & Numbers:** Use a monospaced font (JetBrains Mono, Fira Code, or `monospace`) for all numbers, coordinates, timestamps, and logs.
- **Labels:** Use a highly legible, dense sans-serif (Inter) for labels. 
- **Sizing:** Text must be small, crisp, and space-efficient. Default data size: `12px` or `0.75rem`.

## 4. Interaction Design
- **Keyboard First:** Every interactive element must have a visible keyboard shortcut (e.g., `[F5] Execute`, `[T] Toggle Overlay`).
- **Hover States:** Functional only. Inverted colors (background becomes text color, text becomes background color) or a strict 1px solid outline. No glowing, fading, or shifting animations.
- **Transitions:** None. State changes should be instant (0ms transition) to emphasize responsiveness and speed.

## 5. Architectural Layout (3-Pane)
1. **Left Sidebar (Ingestion & Parameters - 25% width):** Unified compact dropzone for Baseline/Recon imagery. High-density toggles for target criteria (Craters, Vehicles, Felled Trees). Execution controls.
2. **Center Stage (The Diff Engine - 55% width):** Primary workspace. Idle state shows wireframe map or terminal state. Post-upload shows an advanced viewer (side-by-side or interactive overlay).
3. **Right Sidebar (Telemetry & Output - 20% width):** Real-time system logs, metadata, coordinate readouts (Bounding coordinates, LAT/LON), and export status (e.g., XML generation, ATAK integration).

Every future UI decision must reference this file. Deviations will be rejected.
