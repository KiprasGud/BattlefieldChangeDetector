import { useEffect, useState, useRef, type CSSProperties, type PointerEvent as ReactPointerEvent, type KeyboardEvent } from "react";
import type { ReviewStatus } from "../api";
import { CATEGORY_CODES, type AnalyzeResponse, type Change } from "../types";
import { isTyping, targetId } from "../util";

type Size = { w: number; h: number };

// Natural pixel size of an image (every result image shares image A's frame).
function useNaturalSize(url?: string): Size | null {
  const [size, setSize] = useState<Size | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    const img = new Image();
    img.onload = () => {
      if (alive) setSize({ w: img.naturalWidth, h: img.naturalHeight });
    };
    img.src = url;
    return () => {
      alive = false;
    };
  }, [url]);
  return size;
}

interface Props {
  data: AnalyzeResponse;
  selectedIndex: number | null;
  onSelectIndex: (index: number | null) => void;
  statuses?: ReviewStatus[]; // review verdict per change (review mode only)
}

type ViewMode = "slider" | "annotated" | "split" | "heatmap";

// Every view with its [1]-[4] shortcut and button label.
const VIEW_MODES: { mode: ViewMode; key: string; label: string }[] = [
  { mode: "slider", key: "1", label: "SLIDER" },
  { mode: "annotated", key: "2", label: "HUD" },
  { mode: "split", key: "3", label: "SPLIT" },
  { mode: "heatmap", key: "4", label: "HEATMAP" },
];

const DRAG_THRESHOLD = 4;

function SafeImg({ src, alt, className, style }: { src?: string; alt: string; className?: string; style?: CSSProperties }) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src) {
    return (
      <div className={`img-missing ${className ?? ""}`} style={style}>
        [ERR] {alt} UNAVAILABLE
      </div>
    );
  }
  return <img src={src} alt={alt} className={className} style={style} draggable={false} onError={() => setFailed(src)} />;
}

function TacticalBoxOverlay({
  changes,
  selectedIndex,
  onSelect,
  statuses,
  natural,
}: {
  changes: Change[];
  selectedIndex: number | null;
  onSelect?: (idx: number) => void;
  statuses?: ReviewStatus[];
  natural?: Size | null;
}) {
  // Boxes are 0-1000 of the image, and object-fit: contain letterboxes the image inside its container, so the
  // layer takes the image's aspect ratio and is fitted the same way (container query units, see .box-layer.fitted).
  const fit = natural ? ({ "--ar": natural.w / natural.h } as CSSProperties) : { inset: 0 };
  return (
    <div className={`box-layer ${natural ? "fitted" : ""}`} style={{ position: "absolute", pointerEvents: "none", ...fit }}>
      {changes.map((c, idx) => {
        const [ymin, xmin, ymax, xmax] = c.box.map((v) => Math.max(0, Math.min(1000, v)) / 10);
        const isSelected = selectedIndex === idx;
        const review = statuses?.[idx] ? `review-${statuses[idx]}` : "";
        const code = c.category ? ` ${CATEGORY_CODES[c.category] ?? "UNK"}` : "";
        const id = targetId(idx);
        return (
          <div
            key={idx}
            data-box={idx}
            className={`tactical-box ${isSelected ? "selected" : ""} ${review}`}
            onClick={onSelect ? () => onSelect(idx) : undefined}
            title={`${id} ${c.type}${c.description ? `\n${c.description}` : ""}`}
            style={{ top: `${ymin}%`, left: `${xmin}%`, width: `${xmax - xmin}%`, height: `${ymax - ymin}%` }}
          >
            <span className="tactical-box-label">[{id}{code}] {c.type}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function ResultViewer({ data, selectedIndex, onSelectIndex, statuses }: Props) {
  const [mode, setMode] = useState<ViewMode>("slider");
  const [sliderPos, setSliderPos] = useState(50);
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.65);
  const containerRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; startX: number; moved: boolean; boxIdx: number | null } | null>(null);
  const rafRef = useRef<number | null>(null);

  const changes = data.result.changes;
  const beforeUrl = data.images.image_a_url || data.images.aligned_b_url;
  const alignedUrl = data.images.aligned_b_url || data.images.annotated_url;
  const annotatedUrl = data.images.annotated_url;
  const heatmapUrl = data.images.heatmap_url;
  const natural = useNaturalSize(alignedUrl);

  const view: ViewMode = mode === "heatmap" && !heatmapUrl ? "slider" : mode;
  const toggleSelect = (idx: number) => onSelectIndex(selectedIndex === idx ? null : idx);

  const posFromClientX = (clientX: number) => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (rect && rect.width > 0) {
        setSliderPos(Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100)));
      }
      rafRef.current = null;
    });
  };

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

  // [1]-[4] switch the view; ignored while typing or with a modifier held.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey || isTyping(e.target)) return;
      const next = VIEW_MODES.find((v) => v.key === e.key)?.mode;
      if (!next || (next === "heatmap" && !heatmapUrl)) return;
      e.preventDefault();
      setMode(next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [heatmapUrl]);

  const onHandleKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 10 : 2;
    if (e.key === "ArrowLeft") setSliderPos((p) => Math.max(0, p - step));
    else if (e.key === "ArrowRight") setSliderPos((p) => Math.min(100, p + step));
    else if (e.key === "Home") setSliderPos(0);
    else if (e.key === "End") setSliderPos(100);
    else return;
    e.preventDefault();
  };

  // The same box layer sits on top of whichever view is shown.
  const overlay = (
    <TacticalBoxOverlay changes={changes} selectedIndex={selectedIndex} onSelect={toggleSelect} statuses={statuses} natural={natural} />
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="view-controls">
        {VIEW_MODES.filter((v) => v.mode !== "heatmap" || heatmapUrl).map((v) => (
          <button key={v.mode} className={`tactical-toggle ${view === v.mode ? "active" : ""}`} onClick={() => setMode(v.mode)}>
            [{v.key}] {v.label}
          </button>
        ))}
      </div>

      <div style={{ flexGrow: 1, position: "relative" }}>
        {view === "slider" && (
          <div
            ref={containerRef}
            className="diff-container"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => (drag.current = null)}
            style={{ cursor: "ew-resize", touchAction: "pan-y", height: "100%" }}
          >
            <SafeImg src={alignedUrl} alt="Aligned recon" className="diff-layer" />

            <div className="diff-layer" style={{ clipPath: `inset(0 ${100 - sliderPos}% 0 0)` }}>
              <SafeImg src={beforeUrl} alt="Baseline" className="diff-layer" />
            </div>

            {overlay}

            <div
              className="slider-divider"
              style={{ left: `${sliderPos}%` }}
              role="slider"
              tabIndex={0}
              aria-label="Before/after divider"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(sliderPos)}
              onKeyDown={onHandleKey}
            />

            <div className="diff-label" style={{ left: "12px" }}>BASELINE</div>
            <div className="diff-label" style={{ right: "12px", color: "var(--accent-exec)" }}>RECON</div>
          </div>
        )}

        {view === "annotated" && (
          <div className="diff-container" style={{ height: "100%" }}>
            <SafeImg src={annotatedUrl} alt="Annotated output" className="diff-layer" />
            {overlay}
          </div>
        )}

        {view === "split" && (
          <div className="diff-container" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2px", background: "var(--border-main)", height: "100%" }}>
            <div className="fit-host" style={{ position: "relative", background: "var(--bg-app)" }}>
              <SafeImg src={beforeUrl} alt="Baseline" className="diff-layer" />
              <div className="diff-label" style={{ left: "12px" }}>BASELINE</div>
            </div>
            <div className="fit-host" style={{ position: "relative", background: "var(--bg-app)" }}>
              <SafeImg src={annotatedUrl} alt="Annotated" className="diff-layer" />
              {overlay}
              <div className="diff-label" style={{ left: "12px", color: "var(--accent-exec)" }}>RECON</div>
            </div>
          </div>
        )}

        {view === "heatmap" && heatmapUrl && (
          <div className="diff-container" style={{ height: "100%" }}>
            <SafeImg src={alignedUrl} alt="Base" className="diff-layer" />
            <SafeImg src={heatmapUrl} alt="Heatmap" className="diff-layer" style={{ opacity: heatmapOpacity, mixBlendMode: "screen" }} />
            {overlay}

            <div className="heatmap-opacity">
              <span className="fs-xs mono">HEATMAP OPACITY: {(heatmapOpacity * 100).toFixed(0)}%</span>
              <input
                type="range"
                min="0.1"
                max="1"
                step="0.05"
                value={heatmapOpacity}
                onChange={(e) => setHeatmapOpacity(parseFloat(e.target.value))}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
