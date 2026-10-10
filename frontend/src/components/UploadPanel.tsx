import { useState, useEffect, useRef, type DragEvent } from "react";
import { fetchSamples, fetchImageAsBlob, type SamplePair } from "../api";

const PRESET_CRITERIA = [
  "New vehicle tracks",
  "Craters / digging",
  "Felled trees / clearing",
  "New field cables / lines",
  "Trench lines & fortifications",
  "Camouflage & equipment",
];

const MAX_FILE_MB = 25; // matches MAX_FILE_SIZE_BYTES in backend/app/main.py

interface Props {
  onSubmit: (a: File | Blob, b: File | Blob, criteria: string, lang: string, drawGrid: boolean) => void;
  onError: (message: string) => void;
  loading: boolean;
  lang: string;
  onLangChange: (lang: string) => void;
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const hasPreset = (criteria: string, preset: string) => criteria.toLowerCase().includes(preset.toLowerCase());

/** Returns an error message, or null if the file is acceptable. */
function validateImage(file: File | Blob): string | null {
  if (file.type && !file.type.startsWith("image/")) return "Only image files (PNG, JPEG, …) are accepted.";
  if (file.size > MAX_FILE_MB * 1024 * 1024) return `Image is larger than ${MAX_FILE_MB} MB.`;
  return null;
}

/** Object URL for a blob, revoked when the blob changes or the component unmounts. */
function useObjectUrl(blob: File | Blob | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob]);
  return url;
}

function ImageDrop({
  id,
  title,
  subtitle,
  icon,
  hint,
  accent,
  file,
  disabled,
  onFile,
}: {
  id: string;
  title: string;
  subtitle: string;
  icon: string;
  hint: string;
  accent: string;
  file: File | Blob | null;
  disabled: boolean;
  onFile: (file: File | Blob | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const preview = useObjectUrl(file);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = (f: File | Blob | null) => {
    if (!f) {
      setError(null);
      onFile(null);
      return;
    }
    const err = validateImage(f);
    setError(err);
    if (!err) onFile(f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    accept(e.dataTransfer.files?.[0] ?? null);
  };

  const openPicker = () => !disabled && inputRef.current?.click();

  return (
    <div
      className={`drop-zone${dragging ? " dragging" : ""}`}
      style={{ borderColor: dragging ? "var(--brand-base)" : file ? accent : undefined }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={(e) => {
        // Ignore leave events fired when moving over child elements.
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
    >
      <div className="drop-zone-head">
        <span className="drop-zone-title">
          {title} <span className="dim">({subtitle})</span>
        </span>
        {file && (
          <button type="button" className="link-btn danger" onClick={() => accept(null)} disabled={disabled}>
            Remove
          </button>
        )}
      </div>

      <div
        className={`drop-zone-body${preview ? " has-preview" : ""}`}
        role="button"
        tabIndex={0}
        aria-label={`${preview ? "Replace" : "Upload"} ${title}`}
        onClick={openPicker}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openPicker();
          }
        }}
      >
        {preview ? (
          <>
            <img src={preview} alt={`${title} preview`} draggable={false} />
            <span className="drop-zone-replace">Click or drop to replace</span>
          </>
        ) : (
          <>
            <div className="drop-zone-icon">{icon}</div>
            <span className="muted">Click or drop an image</span>
            <span className="dim xsmall">{hint}</span>
          </>
        )}
      </div>

      {error && <div className="field-error">{error}</div>}

      <input
        id={id}
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => {
          accept(e.target.files?.[0] ?? null);
          // Reset so picking the same file again still fires onChange.
          e.target.value = "";
        }}
      />
    </div>
  );
}

export default function UploadPanel({ onSubmit, onError, loading, lang, onLangChange }: Props) {
  const [a, setA] = useState<File | Blob | null>(null);
  const [b, setB] = useState<File | Blob | null>(null);
  const [criteria, setCriteria] = useState(PRESET_CRITERIA[0]);
  const [drawGrid, setDrawGrid] = useState(true);
  const [samples, setSamples] = useState<SamplePair[]>([]);
  const [loadingSample, setLoadingSample] = useState<string | null>(null);

  useEffect(() => {
    fetchSamples()
      .then(setSamples)
      .catch((err) => console.warn("Could not load samples:", err));
  }, []);

  const loadSample = async (sample: SamplePair) => {
    setLoadingSample(sample.id);
    try {
      const [blobA, blobB] = await Promise.all([fetchImageAsBlob(sample.image_a_url), fetchImageAsBlob(sample.image_b_url)]);
      setA(blobA);
      setB(blobB);
      setCriteria(sample.criteria);
    } catch (err: any) {
      onError(`Could not load sample "${sample.name}": ${err?.message ?? err}`);
    } finally {
      setLoadingSample(null);
    }
  };

  const togglePreset = (preset: string) => {
    if (!criteria.trim()) {
      setCriteria(preset);
    } else if (hasPreset(criteria, preset)) {
      const updated = criteria
        .replace(new RegExp(`(?:,\\s*)?${escapeRegExp(preset)}`, "i"), "")
        .replace(/^\s*,\s*/, "")
        .trim();
      setCriteria(updated);
    } else {
      setCriteria(`${criteria.trim().replace(/,$/, "")}, ${preset}`);
    }
  };

  const canSubmit = Boolean(a && b && criteria.trim()) && !loading;
  const submit = () => {
    if (a && b && canSubmit) onSubmit(a, b, criteria.trim(), lang, drawGrid);
  };

  return (
    <div className="glass-panel panel">
      {/* Sample presets bar */}
      {samples.length > 0 && (
        <div className="section">
          <div className="section-head">
            <span className="mono dim small upper">Quick Demo Pairs</span>
            <span className="dim xsmall">One-click baseline &amp; recon load</span>
          </div>
          <div className="chip-row">
            {samples.map((s) => (
              <button
                key={s.id}
                type="button"
                id={`sample-btn-${s.id}`}
                onClick={() => loadSample(s)}
                disabled={loading || loadingSample !== null}
                className="btn-secondary small"
                title={s.description}
                style={{ borderColor: loadingSample === s.id ? "var(--brand-base)" : undefined }}
              >
                <span className="accent">⚡</span> {s.name}
                {loadingSample === s.id && " (Loading…)"}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Dual Uploaders */}
      <div className="upload-grid">
        <ImageDrop
          id="file-input-a"
          title="Image A"
          subtitle="Past / Baseline"
          icon="📷"
          hint={`PNG, JPEG up to ${MAX_FILE_MB} MB`}
          accent="var(--accent-success)"
          file={a}
          disabled={loading}
          onFile={setA}
        />
        <ImageDrop
          id="file-input-b"
          title="Image B"
          subtitle="Present / Recon"
          icon="🛰️"
          hint="Warped & registered to frame A"
          accent="var(--brand-base)"
          file={b}
          disabled={loading}
          onFile={setB}
        />
      </div>

      {/* Criteria presets */}
      <div className="section">
        <div className="section-head">
          <label htmlFor="criteria-input" className="field-label">
            Reconnaissance Target Criteria
          </label>
          <span className="dim xsmall">Toggle chips or write free-form instructions</span>
        </div>
        <div className="chip-row section">
          {PRESET_CRITERIA.map((p) => {
            const isSelected = hasPreset(criteria, p);
            return (
              <button
                key={p}
                type="button"
                className={`preset-chip${isSelected ? " selected" : ""}`}
                aria-pressed={isSelected}
                onClick={() => togglePreset(p)}
                disabled={loading}
              >
                {isSelected ? "✓ " : "+ "}
                {p}
              </button>
            );
          })}
        </div>

        <textarea
          id="criteria-input"
          className="text-input"
          rows={2}
          value={criteria}
          onChange={(e) => setCriteria(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
          }}
          placeholder="e.g. New vehicle tracks, craters, tree clearance, defensive structures..."
        />
      </div>

      {/* Controls & Submit */}
      <div className="controls-row">
        <div className="controls-left">
          <label className="checkbox-label">
            <input id="grid-toggle" type="checkbox" checked={drawGrid} onChange={(e) => setDrawGrid(e.target.checked)} />
            Overlay 4×4 tactical grid (A1–D4)
          </label>

          <div className="lang-wrap">
            <span className="dim xsmall">Report language:</span>
            <div className="lang-selector" role="group" aria-label="Report language">
              {(["en", "lt"] as const).map((l) => (
                <button
                  key={l}
                  type="button"
                  className={`lang-btn ${lang === l ? "active" : ""}`}
                  aria-pressed={lang === l}
                  onClick={() => onLangChange(l)}
                >
                  {l.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </div>

        <button
          id="analyze-submit-btn"
          type="button"
          disabled={!canSubmit}
          onClick={submit}
          className="btn-primary"
          title={!a || !b ? "Add both images first" : !criteria.trim() ? "Enter search criteria" : "Ctrl+Enter"}
        >
          {loading ? (
            <>
              <span className="status-pulse" /> Running intelligence scan…
            </>
          ) : (
            <>
              <span>🎯</span> Execute Change Detection
            </>
          )}
        </button>
      </div>
    </div>
  );
}
