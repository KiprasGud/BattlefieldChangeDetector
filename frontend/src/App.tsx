import React, { useState } from "react";
import { analyze } from "./api";
import type { AnalyzeResponse } from "./types";
import UploadPanel from "./components/UploadPanel";
import ResultViewer from "./components/ResultViewer";
import ReportPanel from "./components/ReportPanel";

export default function App() {
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<string>("en");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  async function handleAnalyze(a: File | Blob, b: File | Blob, criteria: string, language: string, drawGrid: boolean) {
    setLoading(true);
    setError(null);
    setSelectedIndex(null);
    try {
      const response = await analyze(a, b, criteria, language, drawGrid);
      setData(response);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-icon">
            <span style={{ fontSize: "1.5rem" }}>🛰️</span>
          </div>
          <div>
            <h1 className="brand-title">ŽVALGAS AI</h1>
            <div className="brand-tagline">Battlefield Change Detector • ISR Intelligence</div>
          </div>
        </div>

        <div className="header-actions">
          <div className="system-status">
            <span className="status-pulse" />
            <span>OPERATIONAL</span>
          </div>
        </div>
      </header>

      {/* Main Upload / Config Panel */}
      <UploadPanel
        onSubmit={handleAnalyze}
        loading={loading}
        lang={lang}
        onLangChange={setLang}
      />

      {/* Error notification */}
      {error && (
        <div
          id="error-banner"
          style={{
            background: "rgba(239, 68, 68, 0.1)",
            border: "1px solid rgba(239, 68, 68, 0.4)",
            color: "#fca5a5",
            padding: "14px 20px",
            borderRadius: "8px",
            marginBottom: "24px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "1.2rem" }}>⛔</span>
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            style={{ background: "none", border: "none", color: "#fca5a5", cursor: "pointer", fontSize: "1.1rem" }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Loading Scanning Card */}
      {loading && (
        <div className="glass-panel scanner-overlay" style={{ padding: "40px", textAlign: "center", marginBottom: "28px" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: "14px" }}>📡</div>
          <h3 style={{ fontSize: "1.2rem", fontWeight: 700, marginBottom: "8px", letterSpacing: "0.04em" }}>
            EXECUTING RECONNAISSANCE ANALYSIS
          </h3>
          <p style={{ color: "var(--text-muted)", fontSize: "0.88rem", maxWidth: "480px", margin: "0 auto 16px" }}>
            Computing sub-pixel feature homography, aligning perspective frames, querying multimodal vision model, and generating tactical report...
          </p>
          <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", fontSize: "0.8rem", color: "var(--accent-cyan)", fontFamily: "var(--font-mono)" }}>
            <span className="status-pulse" /> SCANNING SENSORS & INGESTING TELEMETRY
          </div>
        </div>
      )}

      {/* Analysis Results */}
      {data && !loading && (
        <>
          <ResultViewer
            data={data}
            selectedIndex={selectedIndex}
            onSelectIndex={setSelectedIndex}
          />
          <ReportPanel
            data={data}
            selectedIndex={selectedIndex}
            onSelectIndex={setSelectedIndex}
          />
        </>
      )}

      {/* Footer */}
      <footer style={{ marginTop: "48px", paddingTop: "20px", borderTop: "1px solid var(--border-subtle)", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", fontSize: "0.78rem", color: "var(--text-dim)" }}>
        <div>Žvalgas AI • Aerial Reconnaissance & Change Detection System</div>
        <div style={{ fontFamily: "var(--font-mono)" }}>[0–1000] Bounding Coordinates • OpenCV + Gemini 2.5</div>
      </footer>
    </div>
  );
}
