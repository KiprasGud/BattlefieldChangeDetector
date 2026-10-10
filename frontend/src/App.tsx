import React, { useState, useEffect } from "react";
import { analyze, fetchJobsHistory, type JobProgress, type JobHistoryItem } from "./api";
import type { AnalyzeResponse } from "./types";
import UploadPanel from "./components/UploadPanel";
import ResultViewer from "./components/ResultViewer";
import ReportPanel from "./components/ReportPanel";

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued — awaiting slot",
  aligning: "Aligning imagery (OpenCV SIFT / ECC)…",
  heatmap: "Computing change heatmap…",
  ai: "Querying Gemini vision model…",
  render: "Rendering tactical HUD annotations…",
  done: "Complete",
  error: "Error",
};

export default function App() {
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [stageDurations, setStageDurations] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<string>("en");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<JobHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [offlineMode, setOfflineMode] = useState(false);

  async function handleAnalyze(a: File | Blob, b: File | Blob, criteria: string, language: string, drawGrid: boolean) {
    setLoading(true);
    setError(null);
    setSelectedIndex(null);
    setStage("queued");
    setStageDurations({});
    setOfflineMode(false);

    try {
      const response = await analyze(
        a, b, criteria, language, drawGrid,
        (progress: JobProgress) => {
          setStage(progress.stage);
          if (progress.timings) setStageDurations({ ...progress.timings });
        }
      );

      // Detect if mock / offline mode was used
      const warnings = response.warnings || [];
      if (warnings.some(w => w.toLowerCase().includes("offline") || w.toLowerCase().includes("fixture"))) {
        setOfflineMode(true);
      }
      if (!response.result || !response.images?.annotated_url) {
        setOfflineMode(true);
      }

      setData(response);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
      setStage("");
    }
  }

  function handleOpenHistory(job: JobHistoryItem) {
    if (job.status !== "done" || !job.result) return;
    const response: AnalyzeResponse = {
      job_id: job.job_id,
      result: job.result,
      align_quality: job.align_quality ?? 0,
      align_ok: Boolean(job.align_ok),
      align_method: (job.align_method as any) || "none",
      images: {
        aligned_b_url: job.images?.aligned_b_url || "",
        annotated_url: job.images?.annotated_url || "",
        image_a_url: job.images?.image_a_url,
        heatmap_url: job.images?.heatmap_url,
      },
      timings: job.timings,
      warnings: job.warnings,
    };
    setData(response);
    setSelectedIndex(null);
    setShowHistory(false);
  }

  async function handleLoadHistory() {
    setLoadingHistory(true);
    try {
      const items = await fetchJobsHistory(30);
      setHistory(items);
      setShowHistory(true);
    } catch (e) {
      console.warn("History load failed:", e);
    } finally {
      setLoadingHistory(false);
    }
  }

  // Current active stage index for progress bar
  const STAGES_ORDER = ["queued", "aligning", "heatmap", "ai", "render", "done"];
  const currentStageIdx = STAGES_ORDER.indexOf(stage);

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
          {/* Mission History button */}
          <button
            id="history-btn"
            type="button"
            className="btn-secondary"
            onClick={handleLoadHistory}
            disabled={loadingHistory}
            style={{ fontSize: "0.8rem" }}
          >
            {loadingHistory ? "Loading…" : "📂 Mission History"}
          </button>
          <div className="system-status">
            <span className="status-pulse" />
            <span>OPERATIONAL</span>
          </div>
        </div>
      </header>

      {/* OFFLINE MODE banner */}
      {offlineMode && (
        <div style={{
          background: "rgba(245, 158, 11, 0.1)",
          border: "1px solid rgba(245, 158, 11, 0.4)",
          color: "#fef3c7",
          padding: "10px 18px",
          borderRadius: "8px",
          marginBottom: "20px",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          fontSize: "0.88rem",
        }}>
          <span style={{ fontSize: "1.2rem" }}>🔌</span>
          <strong>OFFLINE MODE (FIXTURE)</strong> — Gemini API unavailable. Results from local fixture data.
        </div>
      )}

      {/* Mission History Drawer */}
      {showHistory && (
        <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
            <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>📂 Mission History</h2>
            <button type="button" onClick={() => setShowHistory(false)} className="btn-secondary" style={{ fontSize: "0.8rem" }}>
              ✕ Close
            </button>
          </div>
          {history.length === 0 ? (
            <div style={{ color: "var(--text-dim)", textAlign: "center", padding: "20px", fontSize: "0.88rem" }}>
              No completed missions found.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {history.map((job) => (
                <div
                  key={job.job_id}
                  onClick={() => handleOpenHistory(job)}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr auto auto",
                    alignItems: "center",
                    gap: "12px",
                    padding: "10px 14px",
                    background: "rgba(15, 23, 42, 0.6)",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "8px",
                    cursor: job.status === "done" ? "pointer" : "default",
                    opacity: job.status === "done" ? 1 : 0.55,
                    transition: "border-color 0.15s ease",
                  }}
                >
                  {/* Status dot */}
                  <span style={{
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    background: job.status === "done" ? "var(--accent-emerald)"
                      : job.status === "error" ? "var(--accent-red)"
                      : "var(--accent-amber)",
                    flexShrink: 0,
                  }} />

                  <div>
                    <div style={{ fontSize: "0.84rem", fontWeight: 600, marginBottom: "2px" }}>
                      {job.criteria || "Untitled mission"}
                    </div>
                    <div style={{ fontSize: "0.72rem", fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                      {new Date(job.created_at + "Z").toLocaleString()} •
                      {job.changes_count != null && ` ${job.changes_count} target(s) •`} {job.lang?.toUpperCase() || "EN"}
                    </div>
                  </div>

                  <span style={{
                    fontSize: "0.72rem",
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-dim)",
                  }}>
                    #{job.job_id.slice(0, 8)}
                  </span>

                  {job.status === "done" && (
                    <span style={{ fontSize: "0.75rem", color: "var(--accent-cyan)" }}>
                      Open →
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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

      {/* Live Stage Progress */}
      {loading && (
        <div className="glass-panel scanner-overlay" style={{ padding: "28px 36px", marginBottom: "28px" }}>
          <div style={{ textAlign: "center", marginBottom: "20px" }}>
            <div style={{ fontSize: "2rem", marginBottom: "10px" }}>📡</div>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 700, letterSpacing: "0.04em", marginBottom: "6px" }}>
              EXECUTING RECONNAISSANCE ANALYSIS
            </h3>
          </div>

          {/* Stage Step Bar */}
          <div style={{ display: "flex", alignItems: "center", gap: "4px", marginBottom: "16px", justifyContent: "center" }}>
            {STAGES_ORDER.filter(s => s !== "done").map((s, idx) => {
              const isActive = s === stage;
              const isDone = currentStageIdx > idx;
              return (
                <React.Fragment key={s}>
                  <div style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: "4px",
                    minWidth: "72px",
                  }}>
                    <div style={{
                      width: "28px",
                      height: "28px",
                      borderRadius: "50%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "0.75rem",
                      fontWeight: 700,
                      background: isDone ? "var(--accent-emerald)"
                        : isActive ? "var(--accent-cyan)"
                        : "rgba(30, 41, 59, 0.8)",
                      color: isDone || isActive ? "#000" : "var(--text-dim)",
                      border: isActive ? "2px solid var(--accent-cyan)" : "1px solid var(--border-subtle)",
                      boxShadow: isActive ? "0 0 10px var(--accent-cyan)" : "none",
                      transition: "all 0.3s ease",
                    }}>
                      {isDone ? "✓" : idx + 1}
                    </div>
                    <span style={{ fontSize: "0.65rem", fontFamily: "var(--font-mono)", color: isActive ? "var(--accent-cyan)" : "var(--text-dim)", textAlign: "center", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                      {s}
                    </span>
                    {stageDurations[s] && (
                      <span style={{ fontSize: "0.6rem", color: "var(--accent-emerald)", fontFamily: "var(--font-mono)" }}>
                        {stageDurations[s].toFixed(2)}s
                      </span>
                    )}
                  </div>
                  {idx < STAGES_ORDER.filter(s => s !== "done").length - 1 && (
                    <div style={{
                      flex: 1,
                      height: "2px",
                      background: isDone ? "var(--accent-emerald)" : "var(--border-subtle)",
                      transition: "background 0.3s ease",
                    }} />
                  )}
                </React.Fragment>
              );
            })}
          </div>

          <p style={{ color: "var(--text-muted)", fontSize: "0.84rem", textAlign: "center", fontFamily: "var(--font-mono)" }}>
            {STAGE_LABELS[stage] || "Initializing…"}
          </p>
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
        <div>Žvalgas AI • Aerial Reconnaissance &amp; Change Detection System</div>
        <div style={{ fontFamily: "var(--font-mono)" }}>[0–1000] Bounding Coordinates • OpenCV + Gemini 2.5</div>
      </footer>
    </div>
  );
}
