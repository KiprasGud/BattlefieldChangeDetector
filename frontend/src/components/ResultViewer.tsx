import React, { useState, useRef, useEffect, useCallback } from "react";
import type { AnalyzeResponse } from "../types";

interface Props {
  data: AnalyzeResponse;
  selectedIndex: number | null;
  onSelectIndex: (index: number | null) => void;
}

type ViewMode = "slider" | "annotated" | "side_by_side" | "heatmap";

export default function ResultViewer({ data, selectedIndex, onSelectIndex }: Props) {
  const [mode, setMode] = useState<ViewMode>("slider");
  const [sliderPos, setSliderPos] = useState(50); // percentage 0-100
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.65);
  const [showHeatmapOverlay, setShowHeatmapOverlay] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fallback image A URL from data or aligned_b if image_a not present
  const imagesMap = data.images as Record<string, string>;
  const beforeUrl = imagesMap["image_a_url"] || data.images.aligned_b_url;
  const afterUrl = data.images.annotated_url;
  const heatmapUrl = imagesMap["heatmap_url"];

  const handlePointerDown = () => setIsDragging(true);

  const handlePointerMove = useCallback((e: MouseEvent | TouchEvent) => {
    if (!isDragging || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const clientX = "touches" in e ? e.touches[0].clientX : e.clientX;
    const pos = ((clientX - rect.left) / rect.width) * 100;
    setSliderPos(Math.max(0, Math.min(100, pos)));
  }, [isDragging]);

  const handlePointerUp = useCallback(() => setIsDragging(false), []);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener("mousemove", handlePointerMove);
      window.addEventListener("mouseup", handlePointerUp);
      window.addEventListener("touchmove", handlePointerMove);
      window.addEventListener("touchend", handlePointerUp);
    }
    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", handlePointerUp);
      window.removeEventListener("touchmove", handlePointerMove);
      window.removeEventListener("touchend", handlePointerUp);
    };
  }, [isDragging, handlePointerMove, handlePointerUp]);

  return (
    <div className="glass-panel" style={{ padding: "24px", marginBottom: "28px" }}>
      {/* Top status bar: Alignment quality & mode tabs */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "14px", marginBottom: "18px" }}>
        {/* Alignment health & quality badge */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "6px 14px",
              borderRadius: "6px",
              background: data.align_ok ? "rgba(16, 185, 129, 0.1)" : "rgba(239, 68, 68, 0.12)",
              border: `1px solid ${data.align_ok ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.4)"}`,
            }}
          >
            <span
              style={{
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                background: data.align_ok ? "var(--accent-emerald)" : "var(--accent-red)",
              }}
            />
            <span style={{ fontSize: "0.82rem", fontFamily: "var(--font-mono)", fontWeight: 600 }}>
              {data.align_ok ? "ALIGNED" : "ALIGNMENT DEGRADED"}
            </span>
            <span style={{ fontSize: "0.78rem", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
              ({(data.align_quality * 100).toFixed(0)}% quality)
            </span>
          </div>

          {/* Alignment method */}
          {data.align_method && (
            <span
              style={{
                fontSize: "0.75rem",
                fontFamily: "var(--font-mono)",
                background: "rgba(30, 41, 59, 0.6)",
                border: "1px solid var(--border-subtle)",
                padding: "4px 8px",
                borderRadius: "4px",
                color: "var(--text-muted)",
              }}
            >
              METHOD: {data.align_method.toUpperCase()}
            </span>
          )}

          <span style={{ fontSize: "0.8rem", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
            MISSION: #{data.job_id}
          </span>
        </div>

        {/* View mode toggle */}
        <div style={{ display: "flex", background: "rgba(15, 23, 42, 0.9)", border: "1px solid var(--border-subtle)", borderRadius: "8px", padding: "3px" }}>
          <button
            type="button"
            id="mode-slider-btn"
            onClick={() => setMode("slider")}
            style={{
              background: mode === "slider" ? "rgba(6, 182, 212, 0.25)" : "transparent",
              color: mode === "slider" ? "var(--accent-cyan)" : "var(--text-muted)",
              border: "none",
              padding: "6px 12px",
              borderRadius: "6px",
              fontSize: "0.8rem",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            ↔ Slider
          </button>
          <button
            type="button"
            id="mode-annotated-btn"
            onClick={() => setMode("annotated")}
            style={{
              background: mode === "annotated" ? "rgba(6, 182, 212, 0.25)" : "transparent",
              color: mode === "annotated" ? "var(--accent-cyan)" : "var(--text-muted)",
              border: "none",
              padding: "6px 12px",
              borderRadius: "6px",
              fontSize: "0.8rem",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            🎯 HUD
          </button>
          <button
            type="button"
            id="mode-side-by-side-btn"
            onClick={() => setMode("side_by_side")}
            style={{
              background: mode === "side_by_side" ? "rgba(6, 182, 212, 0.25)" : "transparent",
              color: mode === "side_by_side" ? "var(--accent-cyan)" : "var(--text-muted)",
              border: "none",
              padding: "6px 12px",
              borderRadius: "6px",
              fontSize: "0.8rem",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            ◫ Split
          </button>
          {heatmapUrl && (
            <button
              type="button"
              id="mode-heatmap-btn"
              onClick={() => setMode("heatmap")}
              style={{
                background: mode === "heatmap" ? "rgba(245, 158, 11, 0.25)" : "transparent",
                color: mode === "heatmap" ? "var(--accent-amber)" : "var(--text-muted)",
                border: "none",
                padding: "6px 12px",
                borderRadius: "6px",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              🔥 Heatmap
            </button>
          )}
        </div>
      </div>

      {/* Warnings Banner */}
      {data.warnings && data.warnings.length > 0 && (
        <div className="warning-banner" style={{ marginBottom: "16px" }}>
          <span style={{ fontSize: "1.2rem" }}>⚠️</span>
          <div>
            <strong>Operational Warnings:</strong>
            <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
              {data.warnings.map((w, idx) => (
                <li key={idx} style={{ fontSize: "0.84rem" }}>{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Timings row */}
      {data.timings && Object.keys(data.timings).length > 0 && (
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center", marginBottom: "14px" }}>
          <span style={{ fontSize: "0.74rem", fontFamily: "var(--font-mono)", color: "var(--text-dim)", textTransform: "uppercase" }}>
            LATENCY:
          </span>
          {Object.entries(data.timings).map(([stage, sec]) => (
            <span
              key={stage}
              style={{
                fontSize: "0.72rem",
                fontFamily: "var(--font-mono)",
                background: "rgba(15, 23, 42, 0.7)",
                border: "1px solid var(--border-subtle)",
                padding: "2px 8px",
                borderRadius: "4px",
                color: stage === "total" ? "var(--accent-cyan)" : "var(--text-muted)",
              }}
            >
              {stage}: {Number(sec).toFixed(2)}s
            </span>
          ))}

          {/* Heatmap overlay toggle when available */}
          {heatmapUrl && mode !== "heatmap" && (
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "10px" }}>
              <label style={{ fontSize: "0.76rem", color: "var(--accent-amber)", display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={showHeatmapOverlay}
                  onChange={(e) => setShowHeatmapOverlay(e.target.checked)}
                  style={{ accentColor: "var(--accent-amber)" }}
                />
                Overlay Change Heatmap
              </label>
              {showHeatmapOverlay && (
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  value={heatmapOpacity}
                  onChange={(e) => setHeatmapOpacity(parseFloat(e.target.value))}
                  style={{ width: "80px", accentColor: "var(--accent-amber)" }}
                  title={`Opacity: ${(heatmapOpacity * 100).toFixed(0)}%`}
                />
              )}
            </div>
          )}
        </div>
      )}

      {/* Main View Area */}
      {mode === "slider" && (
        <div
          ref={containerRef}
          id="slider-container"
          style={{
            position: "relative",
            width: "100%",
            borderRadius: "10px",
            overflow: "hidden",
            userSelect: "none",
            background: "#030712",
            border: "1px solid var(--border-subtle)",
            boxShadow: "0 12px 30px rgba(0, 0, 0, 0.6)",
          }}
        >
          {/* Bottom layer: Annotated Recon Image */}
          <img
            src={afterUrl}
            alt="Annotated After"
            style={{ width: "100%", display: "block", pointerEvents: "none" }}
          />

          {/* Optional Heatmap blend */}
          {showHeatmapOverlay && heatmapUrl && (
            <img
              src={heatmapUrl}
              alt="Heatmap overlay"
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: "100%",
                objectFit: "contain",
                opacity: heatmapOpacity,
                mixBlendMode: "screen",
                pointerEvents: "none",
              }}
            />
          )}

          {/* Top layer: Before Image clipped */}
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              clipPath: `polygon(0 0, ${sliderPos}% 0, ${sliderPos}% 100%, 0 100%)`,
              pointerEvents: "none",
            }}
          >
            <img
              src={beforeUrl}
              alt="Baseline Before"
              style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
            />
          </div>

          {/* Interactive Boxes Overlay Layer */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, pointerEvents: "none" }}>
            {data.result.changes.map((c, idx) => {
              const isSelected = selectedIndex === idx;
              const ymin = c.box[0] / 10;
              const xmin = c.box[1] / 10;
              const ymax = c.box[2] / 10;
              const xmax = c.box[3] / 10;
              return (
                <div
                  key={idx}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectIndex(isSelected ? null : idx);
                  }}
                  style={{
                    position: "absolute",
                    top: `${ymin}%`,
                    left: `${xmin}%`,
                    width: `${xmax - xmin}%`,
                    height: `${ymax - ymin}%`,
                    pointerEvents: "auto",
                    cursor: "pointer",
                    border: isSelected ? "3px solid #00f0ff" : "1px solid rgba(255, 255, 255, 0.2)",
                    boxShadow: isSelected ? "0 0 20px #00f0ff, inset 0 0 12px rgba(0, 240, 255, 0.3)" : "none",
                    borderRadius: "2px",
                    transition: "all 0.15s ease",
                  }}
                >
                  {isSelected && (
                    <div
                      style={{
                        position: "absolute",
                        top: "-26px",
                        left: "0",
                        background: "#00f0ff",
                        color: "#000",
                        fontSize: "0.72rem",
                        fontFamily: "var(--font-mono)",
                        fontWeight: 700,
                        padding: "2px 6px",
                        borderRadius: "3px",
                        whiteSpace: "nowrap",
                      }}
                    >
                      SELECTED TARGET #{idx + 1}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Draggable Divider Handle */}
          <div
            id="slider-divider-handle"
            onMouseDown={handlePointerDown}
            onTouchStart={handlePointerDown}
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${sliderPos}%`,
              transform: "translateX(-50%)",
              width: "4px",
              background: "var(--accent-cyan)",
              cursor: "ew-resize",
              boxShadow: "0 0 12px var(--accent-cyan)",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                width: "36px",
                height: "36px",
                borderRadius: "50%",
                background: "#0f172a",
                border: "2px solid var(--accent-cyan)",
                boxShadow: "0 0 16px rgba(6, 182, 212, 0.8)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "0.75rem",
                color: "var(--accent-cyan)",
              }}
            >
              ↔
            </div>
          </div>

          {/* Left/Right floating labels */}
          <div
            style={{
              position: "absolute",
              top: "12px",
              left: "14px",
              background: "rgba(15, 23, 42, 0.8)",
              border: "1px solid var(--border-subtle)",
              padding: "4px 10px",
              borderRadius: "6px",
              fontSize: "0.74rem",
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
              pointerEvents: "none",
            }}
          >
            ◀ BASELINE (PAST)
          </div>
          <div
            style={{
              position: "absolute",
              top: "12px",
              right: "14px",
              background: "rgba(15, 23, 42, 0.8)",
              border: "1px solid var(--border-subtle)",
              padding: "4px 10px",
              borderRadius: "6px",
              fontSize: "0.74rem",
              fontFamily: "var(--font-mono)",
              color: "var(--accent-cyan)",
              pointerEvents: "none",
            }}
          >
            RECON & ANNOTATIONS ▶
          </div>
        </div>
      )}

      {mode === "annotated" && (
        <div
          style={{
            position: "relative",
            width: "100%",
            borderRadius: "10px",
            overflow: "hidden",
            background: "#030712",
            border: "1px solid var(--border-subtle)",
          }}
        >
          <img src={afterUrl} alt="Annotated Output" style={{ width: "100%", display: "block" }} />

          {/* Optional Heatmap blend */}
          {showHeatmapOverlay && heatmapUrl && (
            <img
              src={heatmapUrl}
              alt="Heatmap overlay"
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: "100%",
                objectFit: "contain",
                opacity: heatmapOpacity,
                mixBlendMode: "screen",
                pointerEvents: "none",
              }}
            />
          )}

          {/* Interactive target overlay boxes */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, pointerEvents: "none" }}>
            {data.result.changes.map((c, idx) => {
              const isSelected = selectedIndex === idx;
              const ymin = c.box[0] / 10;
              const xmin = c.box[1] / 10;
              const ymax = c.box[2] / 10;
              const xmax = c.box[3] / 10;
              return (
                <div
                  key={idx}
                  id={`annotated-box-${idx}`}
                  onClick={() => onSelectIndex(isSelected ? null : idx)}
                  style={{
                    position: "absolute",
                    top: `${ymin}%`,
                    left: `${xmin}%`,
                    width: `${xmax - xmin}%`,
                    height: `${ymax - ymin}%`,
                    pointerEvents: "auto",
                    cursor: "pointer",
                    border: isSelected ? "3px solid #00f0ff" : "1px solid transparent",
                    boxShadow: isSelected ? "0 0 20px #00f0ff, inset 0 0 10px rgba(0, 240, 255, 0.4)" : "none",
                    borderRadius: "2px",
                    transition: "all 0.15s ease",
                  }}
                />
              );
            })}
          </div>
        </div>
      )}

      {mode === "side_by_side" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
          <div>
            <div style={{ fontSize: "0.78rem", fontFamily: "var(--font-mono)", color: "var(--text-muted)", marginBottom: "6px" }}>
              IMAGE A (BASELINE)
            </div>
            <div style={{ borderRadius: "8px", overflow: "hidden", border: "1px solid var(--border-subtle)", background: "#050811" }}>
              <img src={beforeUrl} alt="Baseline" style={{ width: "100%", display: "block" }} />
            </div>
          </div>
          <div>
            <div style={{ fontSize: "0.78rem", fontFamily: "var(--font-mono)", color: "var(--accent-cyan)", marginBottom: "6px" }}>
              IMAGE B (ALIGNED & ANNOTATED)
            </div>
            <div style={{ borderRadius: "8px", overflow: "hidden", border: "1px solid var(--border-subtle)", background: "#050811" }}>
              <img src={afterUrl} alt="Annotated" style={{ width: "100%", display: "block" }} />
            </div>
          </div>
        </div>
      )}

      {mode === "heatmap" && heatmapUrl && (
        <div style={{ borderRadius: "8px", overflow: "hidden", border: "1px solid var(--border-subtle)", background: "#050811", textAlign: "center" }}>
          <img src={heatmapUrl} alt="Diff Change Heatmap" style={{ width: "100%", display: "block" }} />
        </div>
      )}
    </div>
  );
}
