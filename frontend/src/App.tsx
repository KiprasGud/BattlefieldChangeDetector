import { Fragment, useEffect, useRef, useState } from "react";
import {
  analyze,
  checkHealth,
  fetchJobsHistory,
  jobToResponse,
  CancelledError,
  type JobProgress,
  type JobHistoryItem,
} from "./api";
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

// Progress steps shown in the bar, and the key each one uses in `timings` (backend/app/pipeline.py).
const STAGES = [
  { stage: "queued", timing: null },
  { stage: "aligning", timing: "align" },
  { stage: "heatmap", timing: "heatmap" },
  { stage: "ai", timing: "ai" },
  { stage: "render", timing: "render" },
] as const;
const STAGE_ORDER = [...STAGES.map((s) => s.stage as string), "done"];

const HEALTH_INTERVAL_MS = 15000;

function isOfflineResult(r: AnalyzeResponse): boolean {
  return (r.warnings || []).some((w) => /offline|fixture|mock_llm/i.test(w));
}

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
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  // Incremented per analysis; a run whose id is no longer current is ignored (cancel / re-submit).
  const runId = useRef(0);

  useEffect(() => {
    let alive = true;
    const ping = () => checkHealth().then((ok) => alive && setBackendUp(ok));
    ping();
    const t = window.setInterval(ping, HEALTH_INTERVAL_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  async function handleAnalyze(a: File | Blob, b: File | Blob, criteria: string, language: string, drawGrid: boolean) {
    const myRun = ++runId.current;
    const isCancelled = () => runId.current !== myRun;

    setLoading(true);
    setError(null);
    setSelectedIndex(null);
    setStage("queued");
    setStageDurations({});
    setShowHistory(false);

    try {
      const response = await analyze(
        a, b, criteria, language, drawGrid,
        (progress: JobProgress) => {
          setStage(progress.stage);
          if (progress.timings) setStageDurations({ ...progress.timings });
        },
        isCancelled
      );
      if (isCancelled()) return;
      setData(response);
      setBackendUp(true);
    } catch (e: any) {
      if (e instanceof CancelledError || isCancelled()) return;
      setError(e?.message || String(e));
    } finally {
      if (!isCancelled()) {
        setLoading(false);
        setStage("");
      }
    }
  }

  function handleCancel() {
    runId.current++; // the in-flight poll sees this and stops; the backend job finishes on its own
    setLoading(false);
    setStage("");
  }

  function handleOpenHistory(job: JobHistoryItem) {
    if (job.status !== "done" || !job.result) return;
    setData(jobToResponse(job));
    setSelectedIndex(null);
    setShowHistory(false);
  }

  async function handleToggleHistory() {
    if (showHistory) {
      setShowHistory(false);
      return;
    }
    setLoadingHistory(true);
    try {
      setHistory(await fetchJobsHistory(30));
      setShowHistory(true);
    } catch (e: any) {
      setError(e?.message || "Failed to load mission history");
    } finally {
      setLoadingHistory(false);
    }
  }

  const currentStageIdx = STAGE_ORDER.indexOf(stage);
  const offlineMode = data !== null && !loading && isOfflineResult(data);

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
          <button
            id="history-btn"
            type="button"
            className="btn-secondary small"
            onClick={handleToggleHistory}
            disabled={loadingHistory}
            aria-expanded={showHistory}
          >
            {loadingHistory ? "Loading…" : showHistory ? "✕ Close History" : "📂 Mission History"}
          </button>
          <div className={`system-status ${backendUp === false ? "down" : ""}`} title="Backend health (GET /api/health)">
            <span className="status-pulse" />
            <span>{backendUp === null ? "CONNECTING" : backendUp ? "OPERATIONAL" : "BACKEND OFFLINE"}</span>
          </div>
        </div>
      </header>

      {/* OFFLINE MODE banner */}
      {offlineMode && (
        <div className="info-banner">
          <span style={{ fontSize: "1.2rem" }}>🔌</span>
          <span>
            <strong>OFFLINE MODE (FIXTURE)</strong> — Gemini not used. Results come from local fixture data.
          </span>
        </div>
      )}

      {/* Mission History Drawer */}
      {showHistory && (
        <div className="glass-panel panel">
          <div className="section-head">
            <h2 style={{ fontSize: "1rem", fontWeight: 700 }}>📂 Mission History</h2>
            <button type="button" onClick={() => setShowHistory(false)} className="btn-secondary small">
              ✕ Close
            </button>
          </div>
          {history.length === 0 ? (
            <div className="empty-state">No missions found.</div>
          ) : (
            <div className="history-list">
              {history.map((job) => {
                const openable = job.status === "done" && Boolean(job.result);
                return (
                  <div
                    key={job.job_id}
                    className={`history-row${openable ? " openable" : ""}`}
                    role={openable ? "button" : undefined}
                    tabIndex={openable ? 0 : undefined}
                    title={job.status === "error" ? job.error_message || "Failed" : undefined}
                    onClick={() => handleOpenHistory(job)}
                    onKeyDown={(e) => {
                      if (openable && (e.key === "Enter" || e.key === " ")) {
                        e.preventDefault();
                        handleOpenHistory(job);
                      }
                    }}
                  >
                    <span className={`history-dot ${job.status}`} />
                    <div style={{ minWidth: 0 }}>
                      <div className="history-title">{job.criteria || "Untitled mission"}</div>
                      <div className="mono dim xsmall">
                        {new Date(job.created_at + "Z").toLocaleString()}
                        {job.changes_count != null && ` • ${job.changes_count} target(s)`}
                        {` • ${job.lang?.toUpperCase() || "EN"}`}
                        {job.status === "error" && " • FAILED"}
                        {(job.status === "queued" || job.status === "running") && ` • ${job.stage.toUpperCase()}`}
                      </div>
                    </div>
                    <span className="mono dim xsmall">#{job.job_id.slice(0, 8)}</span>
                    {openable && <span className="history-open">Open →</span>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Main Upload / Config Panel */}
      <UploadPanel onSubmit={handleAnalyze} onError={setError} loading={loading} lang={lang} onLangChange={setLang} />

      {/* Error notification */}
      {error && (
        <div id="error-banner" className="error-banner" role="alert">
          <div className="error-banner-body">
            <span style={{ fontSize: "1.2rem" }}>⛔</span>
            <span>{error}</span>
          </div>
          <button type="button" className="icon-btn" aria-label="Dismiss error" onClick={() => setError(null)}>
            ✕
          </button>
        </div>
      )}

      {/* Live Stage Progress */}
      {loading && (
        <div className="glass-panel panel scanner-overlay" aria-live="polite">
          <div style={{ textAlign: "center", marginBottom: "20px" }}>
            <div style={{ fontSize: "2rem", marginBottom: "10px" }}>📡</div>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 700, letterSpacing: "0.04em", marginBottom: "6px" }}>
              EXECUTING RECONNAISSANCE ANALYSIS
            </h3>
          </div>

          <div className="stage-bar">
            {STAGES.map(({ stage: s, timing }, idx) => {
              const isActive = s === stage;
              const isDone = currentStageIdx > idx;
              const secs = timing ? stageDurations[timing] : undefined;
              return (
                <Fragment key={s}>
                  <div className="stage-step">
                    <div className={`stage-dot${isDone ? " done" : isActive ? " active" : ""}`}>{isDone ? "✓" : idx + 1}</div>
                    <span className={`stage-name${isActive ? " active" : ""}`}>{s}</span>
                    {secs != null && <span className="stage-time">{secs.toFixed(2)}s</span>}
                  </div>
                  {idx < STAGES.length - 1 && <div className={`stage-link${isDone ? " done" : ""}`} />}
                </Fragment>
              );
            })}
          </div>

          <p className="mono muted small" style={{ textAlign: "center", marginBottom: "14px" }}>
            {STAGE_LABELS[stage] || "Initializing…"}
          </p>
          <div style={{ textAlign: "center" }}>
            <button type="button" className="btn-secondary small" onClick={handleCancel}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Analysis Results */}
      {data && !loading && (
        <>
          <ResultViewer key={data.job_id} data={data} selectedIndex={selectedIndex} onSelectIndex={setSelectedIndex} />
          <ReportPanel data={data} selectedIndex={selectedIndex} onSelectIndex={setSelectedIndex} />
        </>
      )}

      {/* Footer */}
      <footer className="app-footer">
        <div>Žvalgas AI • Aerial Reconnaissance &amp; Change Detection System</div>
        <div className="mono">[0–1000] Bounding Coordinates • OpenCV + Gemini 3.5 Flash-Lite</div>
      </footer>
    </div>
  );
}
