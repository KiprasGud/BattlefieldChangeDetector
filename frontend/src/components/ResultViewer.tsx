import { useState, useRef, type CSSProperties, type ReactNode, type PointerEvent as ReactPointerEvent, type KeyboardEvent } from "react";
import type { AnalyzeResponse, Change } from "../types";

interface Props {
  data: AnalyzeResponse;
  selectedIndex: number | null;
  onSelectIndex: (index: number | null) => void;
}

type ViewMode = "slider" | "annotated" | "side_by_side" | "heatmap";

// Pointer travel (px) below which a press counts as a click, not a drag.
const DRAG_THRESHOLD = 4;

/** <img> that shows a readable placeholder instead of the broken-image icon. */
function SafeImg({ src, alt, className, style }: { src?: string; alt: string; className?: string; style?: CSSProperties }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src) {
    return (
      <div className={`img-missing ${className ?? ""}`} style={style}>
        {alt}: image unavailable
      </div>
    );
  }
  return <img src={src} alt={alt} className={className} style={style} draggable={false} onError={() => setFailed(src)} />;
}

/** Change boxes positioned in % of the image frame (box = [ymin, xmin, ymax, xmax], 0-1000). */
function BoxOverlay({
  changes,
  selectedIndex,
  onSelect,
  outlined,
}: {
  changes: Change[];
  selectedIndex: number | null;
  onSelect?: (idx: number) => void;
  outlined: boolean; // false when the image already has burned-in boxes
}) {
  return (
    <div className="box-layer">
      {changes.map((c, idx) => {
        const [ymin, xmin, ymax, xmax] = c.box.map((v) => Math.max(0, Math.min(1000, v)) / 10);
        const isSelected = selectedIndex === idx;
        return (
          <div
            key={idx}
            id={`box-${idx}`}
            data-box={idx}
            className={`change-box${isSelected ? " selected" : ""}${outlined ? " outlined" : ""}`}
            title={`#${idx + 1} ${c.type} (${c.confidence})`}
            onClick={onSelect ? () => onSelect(idx) : undefined}
            style={{ top: `${ymin}%`, left: `${xmin}%`, width: `${xmax - xmin}%`, height: `${ymax - ymin}%` }}
          >
            {(outlined || isSelected) && <span className="change-box-label">#{idx + 1}</span>}
          </div>
        );
      })}
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  id,
  accent = "cyan",
  children,
}: {
  active: boolean;
  onClick: () => void;
  id: string;
  accent?: "cyan" | "amber";
  children: ReactNode;
}) {
  return (
    <button type="button" id={id} onClick={onClick} className={`mode-btn ${accent}${active ? " active" : ""}`} aria-pressed={active}>
      {children}
    </button>
  );
}

export default function ResultViewer({ data, selectedIndex, onSelectIndex }: Props) {
  const [mode, setMode] = useState<ViewMode>("slider");
  const [sliderPos, setSliderPos] = useState(50); // percentage 0-100
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.65);
  const [showHeatmapOverlay, setShowHeatmapOverlay] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; startX: number; moved: boolean; boxIdx: number | null } | null>(null);

  const changes = data.result.changes;
  const beforeUrl = data.images.image_a_url || data.images.aligned_b_url;
  const alignedUrl = data.images.aligned_b_url || data.images.annotated_url;
  const annotatedUrl = data.images.annotated_url;
  const heatmapUrl = data.images.heatmap_url;
  // Old jobs may have no heatmap; never leave the viewer empty.
  const view: ViewMode = mode === "heatmap" && !heatmapUrl ? "slider" : mode;

  const toggleSelect = (idx: number) => onSelectIndex(selectedIndex === idx ? null : idx);

  const posFromClientX = (clientX: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    setSliderPos(Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100)));
  };

  // Press anywhere on the image: drag moves the divider, a plain click selects a box (or jumps the divider).
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const boxEl = (e.target as HTMLElement).closest("[data-box]");
    drag.current = {
      id: e.pointerId,
      startX: e.clientX,
      moved: false,
      boxIdx: boxEl ? Number(boxEl.getAttribute("data-box")) : null,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    if (!d.moved && Math.abs(e.clientX - d.startX) < DRAG_THRESHOLD) return;
    d.moved = true;
    posFromClientX(e.clientX);
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    if (d.moved) return;
    if (d.boxIdx !== null) toggleSelect(d.boxIdx);
    else posFromClientX(e.clientX);
  };

  const onHandleKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 10 : 2;
    if (e.key === "ArrowLeft") setSliderPos((p) => Math.max(0, p - step));
    else if (e.key === "ArrowRight") setSliderPos((p) => Math.min(100, p + step));
    else if (e.key === "Home") setSliderPos(0);
    else if (e.key === "End") setSliderPos(100);
    else return;
    e.preventDefault();
  };

  const heatmapLayer =
    showHeatmapOverlay && heatmapUrl ? (
      <img src={heatmapUrl} alt="" className="layer-fill" draggable={false} style={{ opacity: heatmapOpacity, mixBlendMode: "screen" }} />
    ) : null;

  return (
    <div id="result-viewer" className="glass-panel panel">
      {/* Top status bar: Alignment quality & mode tabs */}
      <div className="viewer-toolbar">
        <div className="viewer-meta">
          <div className={`align-badge ${data.align_ok ? "ok" : "bad"}`}>
            <span className="dot" />
            <span className="align-badge-text">{data.align_ok ? "ALIGNED" : "ALIGNMENT DEGRADED"}</span>
            <span className="mono dim small">({(data.align_quality * 100).toFixed(0)}% quality)</span>
          </div>
          {data.align_method && <span className="chip mono">METHOD: {data.align_method.toUpperCase()}</span>}
          <span className="mono dim small">MISSION: #{data.job_id}</span>
        </div>

        <div className="mode-group" role="group" aria-label="View mode">
          <ModeButton id="mode-slider-btn" active={view === "slider"} onClick={() => setMode("slider")}>↔ Slider</ModeButton>
          <ModeButton id="mode-annotated-btn" active={view === "annotated"} onClick={() => setMode("annotated")}>🎯 HUD</ModeButton>
          <ModeButton id="mode-side-by-side-btn" active={view === "side_by_side"} onClick={() => setMode("side_by_side")}>◫ Split</ModeButton>
          {heatmapUrl && (
            <ModeButton id="mode-heatmap-btn" accent="amber" active={view === "heatmap"} onClick={() => setMode("heatmap")}>
              🔥 Heatmap
            </ModeButton>
          )}
        </div>
      </div>

      {/* Warnings Banner */}
      {data.warnings && data.warnings.length > 0 && (
        <div className="warning-banner">
          <span style={{ fontSize: "1.2rem" }}>⚠️</span>
          <div>
            <strong>Operational Warnings:</strong>
            <ul className="warning-list">
              {data.warnings.map((w, idx) => (
                <li key={idx}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Timings + heatmap overlay controls */}
      {((data.timings && Object.keys(data.timings).length > 0) || (heatmapUrl && view !== "heatmap")) && (
        <div className="viewer-subbar">
          {data.timings && Object.keys(data.timings).length > 0 && (
            <div className="timings">
              <span className="mono dim xsmall upper">LATENCY:</span>
              {Object.entries(data.timings).map(([stage, sec]) => (
                <span key={stage} className={`timing-chip mono${stage === "total" ? " total" : ""}`}>
                  {stage}: {Number(sec).toFixed(2)}s
                </span>
              ))}
            </div>
          )}

          {heatmapUrl && view !== "heatmap" && view !== "side_by_side" && (
            <div className="heatmap-controls">
              <label>
                <input type="checkbox" checked={showHeatmapOverlay} onChange={(e) => setShowHeatmapOverlay(e.target.checked)} />
                Overlay change heatmap
              </label>
              {showHeatmapOverlay && (
                <input
                  type="range"
                  min="0.1"
                  max="1"
                  step="0.05"
                  value={heatmapOpacity}
                  onChange={(e) => setHeatmapOpacity(parseFloat(e.target.value))}
                  aria-label="Heatmap opacity"
                  title={`Opacity: ${(heatmapOpacity * 100).toFixed(0)}%`}
                />
              )}
            </div>
          )}
        </div>
      )}

      {/* Main View Area */}
      {view === "slider" && (
        <div
          ref={containerRef}
          id="slider-container"
          className="image-frame slider-frame"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => (drag.current = null)}
        >
          {/* Bottom layer: aligned recon (clean, boxes come from the overlay) */}
          <SafeImg src={alignedUrl} alt="Aligned recon" className="layer-base" />
          {heatmapLayer}

          {/* Top layer: baseline clipped to the left of the divider */}
          <div className="layer-fill" style={{ clipPath: `inset(0 ${100 - sliderPos}% 0 0)` }}>
            <SafeImg src={beforeUrl} alt="Baseline" className="layer-fill" />
          </div>

          <BoxOverlay changes={changes} selectedIndex={selectedIndex} outlined />

          {/* Divider */}
          <div
            id="slider-divider-handle"
            className="slider-handle"
            style={{ left: `${sliderPos}%` }}
            role="slider"
            tabIndex={0}
            aria-label="Before/after divider"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(sliderPos)}
            onKeyDown={onHandleKey}
          >
            <div className="slider-knob">↔</div>
          </div>

          <div className="frame-label left">◀ BASELINE (PAST)</div>
          <div className="frame-label right accent">RECON (ALIGNED) ▶</div>
        </div>
      )}

      {view === "annotated" && (
        <div className="image-frame">
          <SafeImg src={annotatedUrl} alt="Annotated output" className="layer-base" />
          {heatmapLayer}
          <BoxOverlay changes={changes} selectedIndex={selectedIndex} onSelect={toggleSelect} outlined={false} />
        </div>
      )}

      {view === "side_by_side" && (
        <div className="split-view">
          <div>
            <div className="split-label mono">IMAGE A (BASELINE)</div>
            <div className="image-frame">
              <SafeImg src={beforeUrl} alt="Baseline" className="layer-base" />
            </div>
          </div>
          <div>
            <div className="split-label mono accent">IMAGE B (ALIGNED &amp; ANNOTATED)</div>
            <div className="image-frame">
              <SafeImg src={annotatedUrl} alt="Annotated" className="layer-base" />
              <BoxOverlay changes={changes} selectedIndex={selectedIndex} onSelect={toggleSelect} outlined={false} />
            </div>
          </div>
        </div>
      )}

      {view === "heatmap" && heatmapUrl && (
        <div className="image-frame">
          <SafeImg src={heatmapUrl} alt="Change heatmap" className="layer-base" />
          <BoxOverlay changes={changes} selectedIndex={selectedIndex} onSelect={toggleSelect} outlined />
        </div>
      )}
    </div>
  );
}
