import React, { useState, useEffect, useRef } from "react";
import { fetchSamples, fetchImageAsBlob, type SamplePair } from "../api";

const PRESET_CRITERIA = [
  "New vehicle tracks",
  "Craters / digging",
  "Felled trees / clearing",
  "New field cables / lines",
  "Trench lines & fortifications",
  "Camouflage & equipment",
];

interface Props {
  onSubmit: (a: File | Blob, b: File | Blob, criteria: string, lang: string, drawGrid: boolean) => void;
  loading: boolean;
  lang: string;
  onLangChange: (lang: string) => void;
}

export default function UploadPanel({ onSubmit, loading, lang, onLangChange }: Props) {
  const [a, setA] = useState<File | Blob | null>(null);
  const [b, setB] = useState<File | Blob | null>(null);
  const [aPreview, setAPreview] = useState<string | null>(null);
  const [bPreview, setBPreview] = useState<string | null>(null);
  const [criteria, setCriteria] = useState(PRESET_CRITERIA[0]);
  const [drawGrid, setDrawGrid] = useState(true);
  const [samples, setSamples] = useState<SamplePair[]>([]);
  const [loadingSample, setLoadingSample] = useState<string | null>(null);

  const fileInputARef = useRef<HTMLInputElement>(null);
  const fileInputBRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchSamples()
      .then(setSamples)
      .catch((err) => console.warn("Could not load samples:", err));
  }, []);

  const handleSetA = (file: File | Blob | null) => {
    setA(file);
    if (aPreview) URL.revokeObjectURL(aPreview);
    setAPreview(file ? URL.createObjectURL(file) : null);
  };

  const handleSetB = (file: File | Blob | null) => {
    setB(file);
    if (bPreview) URL.revokeObjectURL(bPreview);
    setBPreview(file ? URL.createObjectURL(file) : null);
  };

  const loadSample = async (sample: SamplePair) => {
    setLoadingSample(sample.id);
    try {
      const [blobA, blobB] = await Promise.all([
        fetchImageAsBlob(sample.image_a_url),
        fetchImageAsBlob(sample.image_b_url),
      ]);
      handleSetA(blobA);
      handleSetB(blobB);
      setCriteria(sample.criteria);
    } catch (err) {
      console.error("Failed to load sample:", err);
    } finally {
      setLoadingSample(null);
    }
  };

  const togglePreset = (preset: string) => {
    if (!criteria.trim()) {
      setCriteria(preset);
    } else if (criteria.includes(preset)) {
      const updated = criteria
        .replace(new RegExp(`(?:,\\s*)?${preset}`), "")
        .replace(/^,\s*/, "")
        .trim();
      setCriteria(updated || preset);
    } else {
      setCriteria(`${criteria}, ${preset}`);
    }
  };

  return (
    <div className="glass-panel" style={{ padding: "24px", marginBottom: "28px" }}>
      {/* Sample presets bar */}
      {samples.length > 0 && (
        <div style={{ marginBottom: "20px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
            <span style={{ fontSize: "0.8rem", fontFamily: "var(--font-mono)", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Quick Demo Pairs
            </span>
            <span style={{ fontSize: "0.74rem", color: "var(--text-dim)" }}>
              One-click baseline & recon load
            </span>
          </div>
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            {samples.map((s) => (
              <button
                key={s.id}
                type="button"
                id={`sample-btn-${s.id}`}
                onClick={() => loadSample(s)}
                disabled={loading || loadingSample !== null}
                className="btn-secondary"
                style={{
                  fontSize: "0.82rem",
                  borderColor: loadingSample === s.id ? "var(--accent-cyan)" : "var(--border-subtle)",
                }}
              >
                <span style={{ color: "var(--accent-cyan)" }}>⚡</span> {s.name}
                {loadingSample === s.id && " (Loading...)"}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Dual Uploaders */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "20px", marginBottom: "22px" }}>
        {/* Baseline (A) */}
        <div
          style={{
            background: "rgba(15, 23, 42, 0.6)",
            border: `1px dashed ${a ? "var(--accent-emerald)" : "var(--border-subtle)"}`,
            borderRadius: "10px",
            padding: "16px",
            textAlign: "center",
            position: "relative",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <span style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--text-main)" }}>
              Image A <span style={{ color: "var(--text-dim)", fontWeight: 400 }}>(Past / Baseline)</span>
            </span>
            {a && (
              <button
                type="button"
                onClick={() => handleSetA(null)}
                style={{ background: "none", border: "none", color: "var(--accent-red)", cursor: "pointer", fontSize: "0.75rem" }}
              >
                Remove
              </button>
            )}
          </div>

          {aPreview ? (
            <div style={{ height: "160px", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", borderRadius: "6px", background: "#050811" }}>
              <img src={aPreview} alt="Baseline preview" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
            </div>
          ) : (
            <div
              onClick={() => fileInputARef.current?.click()}
              style={{
                height: "160px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                background: "rgba(10, 15, 26, 0.4)",
                borderRadius: "6px",
              }}
            >
              <div style={{ fontSize: "2rem", color: "var(--text-dim)", marginBottom: "8px" }}>📷</div>
              <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Upload Baseline Image</span>
              <span style={{ fontSize: "0.72rem", color: "var(--text-dim)", marginTop: "4px" }}>PNG, JPEG up to 25MB</span>
            </div>
          )}
          <input
            id="file-input-a"
            ref={fileInputARef}
            type="file"
            accept="image/*"
            style={{ display: "none" }}
            onChange={(e) => handleSetA(e.target.files?.[0] ?? null)}
          />
        </div>

        {/* Present (B) */}
        <div
          style={{
            background: "rgba(15, 23, 42, 0.6)",
            border: `1px dashed ${b ? "var(--accent-cyan)" : "var(--border-subtle)"}`,
            borderRadius: "10px",
            padding: "16px",
            textAlign: "center",
            position: "relative",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <span style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--text-main)" }}>
              Image B <span style={{ color: "var(--text-dim)", fontWeight: 400 }}>(Present / Recon)</span>
            </span>
            {b && (
              <button
                type="button"
                onClick={() => handleSetB(null)}
                style={{ background: "none", border: "none", color: "var(--accent-red)", cursor: "pointer", fontSize: "0.75rem" }}
              >
                Remove
              </button>
            )}
          </div>

          {bPreview ? (
            <div style={{ height: "160px", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", borderRadius: "6px", background: "#050811" }}>
              <img src={bPreview} alt="Recon preview" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
            </div>
          ) : (
            <div
              onClick={() => fileInputBRef.current?.click()}
              style={{
                height: "160px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                background: "rgba(10, 15, 26, 0.4)",
                borderRadius: "6px",
              }}
            >
              <div style={{ fontSize: "2rem", color: "var(--text-dim)", marginBottom: "8px" }}>🛰️</div>
              <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Upload Recon Image</span>
              <span style={{ fontSize: "0.72rem", color: "var(--text-dim)", marginTop: "4px" }}>Warps & registers to frame A</span>
            </div>
          )}
          <input
            id="file-input-b"
            ref={fileInputBRef}
            type="file"
            accept="image/*"
            style={{ display: "none" }}
            onChange={(e) => handleSetB(e.target.files?.[0] ?? null)}
          />
        </div>
      </div>

      {/* Criteria presets */}
      <div style={{ marginBottom: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
          <label style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--text-main)" }}>
            Reconnaissance Target Criteria
          </label>
          <span style={{ fontSize: "0.75rem", color: "var(--text-dim)" }}>
            Select chips to append or write free-form instructions
          </span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "10px" }}>
          {PRESET_CRITERIA.map((p) => {
            const isSelected = criteria.includes(p);
            return (
              <button
                key={p}
                type="button"
                onClick={() => togglePreset(p)}
                style={{
                  background: isSelected ? "rgba(6, 182, 212, 0.16)" : "rgba(30, 41, 59, 0.45)",
                  borderColor: isSelected ? "var(--accent-cyan)" : "var(--border-subtle)",
                  color: isSelected ? "var(--accent-cyan)" : "var(--text-muted)",
                  borderWidth: "1px",
                  borderStyle: "solid",
                  padding: "5px 12px",
                  borderRadius: "6px",
                  fontSize: "0.78rem",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                {isSelected ? "✓ " : "+ "}
                {p}
              </button>
            );
          })}
        </div>

        <textarea
          id="criteria-input"
          rows={2}
          value={criteria}
          onChange={(e) => setCriteria(e.target.value)}
          placeholder="e.g. New vehicle tracks, craters, tree clearance, defensive structures..."
          style={{
            width: "100%",
            background: "rgba(10, 15, 26, 0.8)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "8px",
            color: "var(--text-main)",
            padding: "10px 14px",
            fontSize: "0.88rem",
            fontFamily: "var(--font-sans)",
            outline: "none",
            resize: "vertical",
          }}
        />
      </div>

      {/* Controls & Submit */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
          {/* Grid overlay toggle */}
          <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "0.82rem", color: "var(--text-muted)" }}>
            <input
              id="grid-toggle"
              type="checkbox"
              checked={drawGrid}
              onChange={(e) => setDrawGrid(e.target.checked)}
              style={{ cursor: "pointer", accentColor: "var(--accent-cyan)" }}
            />
            Overlay 4×4 Tactical Grid (A1–D4)
          </label>

          {/* Lang selector */}
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "0.78rem", color: "var(--text-dim)" }}>Report Language:</span>
            <div className="lang-selector">
              <button
                type="button"
                className={`lang-btn ${lang === "en" ? "active" : ""}`}
                onClick={() => onLangChange("en")}
              >
                EN
              </button>
              <button
                type="button"
                className={`lang-btn ${lang === "lt" ? "active" : ""}`}
                onClick={() => onLangChange("lt")}
              >
                LT
              </button>
            </div>
          </div>
        </div>

        <button
          id="analyze-submit-btn"
          type="button"
          disabled={!a || !b || loading || !criteria.trim()}
          onClick={() => a && b && onSubmit(a, b, criteria, lang, drawGrid)}
          className="btn-primary"
        >
          {loading ? (
            <>
              <span className="status-pulse" /> Running Intelligence Scan...
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
