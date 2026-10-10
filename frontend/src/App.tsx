import { useEffect, useRef, useState } from "react";
import { analyze, checkHealth, fetchPresets, CancelledError, type JobProgress, type Preset } from "./api";
import type { AnalyzeResponse } from "./types";
import ResultViewer from "./components/ResultViewer";
import ReviewDashboard from "./components/ReviewDashboard";

const HEALTH_INTERVAL_MS = 15000;

type View = "analyze" | "review";
type Theme = "dark" | "light" | "nvg";

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
};

export default function App() {
  // "#review" opens the review dashboard directly (bookmarkable).
  const [view, setViewState] = useState<View>(window.location.hash === "#review" ? "review" : "analyze");
  const setView = (next: View) => {
    setViewState(next);
    window.history.replaceState(null, "", next === "review" ? "#review" : window.location.pathname);
  };
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [theme, setTheme] = useState<Theme>("dark");

  // Tactical State
  const [fileA, setFileA] = useState<File | null>(null);
  const [fileB, setFileB] = useState<File | null>(null);
  // Pre-made target classes (ids from GET /api/presets); the backend sends each label as plain query text.
  const [presets, setPresets] = useState<Preset[]>([]);
  const [criteria, setCriteria] = useState<string[]>([]);
  const [customQuery, setCustomQuery] = useState<string>("");

  const toggleCriteria = (val: string) => {
    setCriteria(prev =>
      prev.includes(val) ? prev.filter(c => c !== val) : [...prev, val]
    );
  };
  const [logs, setLogs] = useState<string[]>(["[SYS] Terminal initialized."]);
  const [selectedChangeIdx, setSelectedChangeIdx] = useState<number | null>(null);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const queryRef = useRef<HTMLInputElement>(null);
  const runId = useRef(0);
  const purgeArmedTime = useRef<number>(0);

  const [inspectorVisible, setInspectorVisible] = useState(false);
  const [xmlPreview, setXmlPreview] = useState<string>("");

  const addLog = (msg: string) => {
    setLogs(prev => [...prev, `[${new Date().toISOString().split('T')[1].slice(0,11)}] ${msg}`]);
  };

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "instant" });
    }
  }, [logs]);

  useEffect(() => {
    document.body.className = theme === "dark" ? "" : `theme-${theme}`;
  }, [theme]);

  useEffect(() => {
    fetchPresets()
      .then(setPresets)
      .catch((e) => addLog(`[ERR] TARGET CLASSES UNAVAILABLE: ${e?.message || e}`));
  }, []);

  useEffect(() => {
    let alive = true;
    const ping = () => checkHealth().then((ok) => {
      if (alive) {
        setBackendUp(prev => {
          if (prev !== null && prev && !ok) addLog("[ERR] BACKEND CONNECTION LOST");
          if (prev !== null && !prev && ok) addLog("[SYS] BACKEND CONNECTION RESTORED");
          return ok;
        });
      }
    });
    ping();
    const t = window.setInterval(ping, HEALTH_INTERVAL_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  const handlePurge = () => {
    const now = Date.now();
    if (now - purgeArmedTime.current < 1000) {
      setFileA(null);
      setFileB(null);
      setData(null);
      setSelectedChangeIdx(null);
      setStage("");
      setLoading(false);
      setInspectorVisible(false);
      addLog("[WARN] BUFFER PURGED. TERMINAL RESET.");
      purgeArmedTime.current = 0;
    } else {
      addLog("[WARN] PURGE BUFFER ARMED. DOUBLE-TAP ESC TO EXECUTE.");
      purgeArmedTime.current = now;
    }
  };

  const toggleLight = () => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    addLog(`[SYS] ${next.toUpperCase()} MODE ENGAGED.`);
  };

  const toggleNvg = () => {
    const next = theme === "nvg" ? "dark" : "nvg";
    setTheme(next);
    addLog(next === "nvg" ? "[SYS] NIGHT VISION (NVG) MODE ENGAGED." : "[SYS] DARK MODE ENGAGED.");
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (e.altKey && key === "n") {
        e.preventDefault();
        toggleNvg();
      } else if (e.altKey && key === "s") {
        e.preventDefault();
        toggleLight();
      } else if (e.altKey && key === "r") {
        e.preventDefault();
        setView("review");
      } else if (e.altKey && key === "a") {
        e.preventDefault();
        setView("analyze");
      } else if (view !== "analyze") {
        return;
      } else if (e.key === "F5" || (e.ctrlKey && e.key === "Enter")) {
        e.preventDefault();
        handleExecute();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handlePurge();
      } else if (e.altKey && /^Digit[1-9]$/.test(e.code)) {
        const preset = presets[Number(e.code.slice(5)) - 1];
        if (!preset) return;
        e.preventDefault();
        toggleCriteria(preset.id);
      } else if (e.altKey && key === "b") {
        e.preventDefault();
        document.getElementById("file-a")?.click();
      } else if (e.altKey && key === "c") {
        e.preventDefault();
        document.getElementById("file-b")?.click();
      } else if (e.altKey && key === "x") {
        e.preventDefault();
        handleExportXML();
      } else if (e.altKey && key === "j") {
        e.preventDefault();
        handleExportJSON();
      } else if (e.altKey && key === "i") {
        e.preventDefault();
        setInspectorVisible(v => !v);
      } else if (e.key === "/" && !isTyping(e.target)) {
        e.preventDefault();
        queryRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const ingest = (file: File | undefined, label: "Baseline" | "Recon", set: (f: File) => void) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      addLog(`[ERR] ${label.toUpperCase()} INGEST FAILED. INVALID FORMAT.`);
      return;
    }
    set(file);
    addLog(`[INGEST] ${label} loaded: ${file.name}`);
  };

  const handleExecute = async () => {
    if (!fileA || !fileB) {
      addLog("[ERR] Missing imagery for execution.");
      return;
    }
    const query = customQuery.trim();
    if (!criteria.length && !query) {
      addLog("[ERR] No target class selected and no custom query.");
      return;
    }
    const myRun = ++runId.current;
    const isCancelled = () => runId.current !== myRun;

    setLoading(true);
    setError(null);
    setData(null);
    setSelectedChangeIdx(null);
    setStage("queued");
    addLog(`[EXEC] AI scan: ${[...criteria, ...(query ? ["custom query"] : [])].join(", ")}`);

    // Progress is polled every 400 ms: announce the AI phase once, not on every poll.
    let announcedAi = false;
    try {
      const response = await analyze(
        fileA, fileB, { presets: criteria, query }, "en", false,
        (progress: JobProgress) => {
          setStage(progress.stage);
          if (progress.stage === "ai" && !announcedAi) {
            announcedAi = true;
            addLog("[PROC] ANALYZING DATA");
          }
        },
        isCancelled
      );
      if (isCancelled()) return;
      setData(response);
      response.warnings?.forEach(w => addLog(`[WARN] ${w}`));
      addLog(`[SUCCESS] Analysis complete. Targets found: ${response.result.changes.length}`);
    } catch (e: any) {
      if (e instanceof CancelledError || isCancelled()) return;
      setError(e?.message || String(e));
      addLog(`[ERR] EXECUTION FAILED: ${e?.message || String(e)}`);
    } finally {
      if (!isCancelled()) {
        setLoading(false);
        setStage("");
      }
    }
  };

  useEffect(() => {
    if (!data) {
      setXmlPreview("");
      return;
    }
    const now = new Date();
    const timeStr = now.toISOString();
    const staleStr = new Date(now.getTime() + 10 * 60000).toISOString();

    let xml = `<?xml version="1.0" encoding="UTF-8"?>\n<events>\n`;
    data.result.changes.forEach((c, i) => {
      const uid = `ZVALGAS-${data.job_id}-TRGT-${i+1}`;
      // CoT type: hostile ground unit when vehicle classes were searched, generic hostile ground otherwise
      const cotType = criteria.includes("vehicles") || criteria.includes("tracks") ? "a-h-G-U-C" : "a-h-G";
      xml += `  <event version="2.0" uid="${uid}" type="${cotType}" time="${timeStr}" start="${timeStr}" stale="${staleStr}" how="m-g">\n`;
      xml += `    <point lat="0.0" lon="0.0" hae="0.0" ce="9999" le="9999" />\n`;
      xml += `    <detail>\n`;
      xml += `      <contact callsign="TRGT-${String(i+1).padStart(2, '0')}" />\n`;
      xml += `      <remarks>Bounds: [${c.box.map(Math.round).join(', ')}]</remarks>\n`;
      xml += `    </detail>\n`;
      xml += `  </event>\n`;
    });
    xml += `</events>`;
    setXmlPreview(xml);
  }, [data, criteria]);

  const handleExportXML = () => {
    if (!data || !xmlPreview) return;
    const blob = new Blob([xmlPreview], { type: "text/xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `zvalgas_export_${data.job_id}.xml`;
    a.click();
    URL.revokeObjectURL(url);
    addLog("[SYS] XML Payload generated & downloaded.");
  };

  const handleExportJSON = () => {
    if (!data) return;
    const payload = {
      job_id: data.job_id,
      timestamp: new Date().toISOString(),
      targets: data.result.changes.map((c, i) => ({
        id: `TRGT-${String(i+1).padStart(2, '0')}`,
        box: c.box
      }))
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `zvalgas_export_${data.job_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
    addLog("[SYS] JSON Payload generated & downloaded.");
  };

  if (view === "review") {
    return <ReviewDashboard onExit={() => setView("analyze")} />;
  }

  const dropzone = (id: string, label: "Baseline" | "Recon", file: File | null, set: (f: File) => void) => (
    <div
      className="tactical-dropzone"
      onDragOver={e => e.preventDefault()}
      onDrop={e => {
        e.preventDefault();
        ingest(e.dataTransfer.files?.[0], label, set);
      }}
      onClick={() => document.getElementById(id)?.click()}
    >
      <span className="dropzone-label">{file ? file.name : "DRAG & DROP OR CLICK"}</span>
      <input type="file" id={id} accept="image/*" hidden onChange={e => {
        ingest(e.target.files?.[0], label, set);
        e.target.value = "";
      }} />
    </div>
  );

  return (
    <div className="terminal-layout">
      {/* LEFT PANE: INGESTION & PARAMETERS */}
      <aside className="pane">
        <div className="pane-header">
          <div className="pane-title text-success">ŽVALGAS-SYS // INGESTION</div>
          <div className={`fs-xs mono ${backendUp ? "text-success" : "text-danger"}`}>
            {backendUp ? "UPLINK: OK" : "UPLINK: FAIL"}
          </div>
        </div>

        <div className="pane-content">
          <div className="toggle-grid">
            <button className="tactical-toggle active">[ALT+A] ANALYZE</button>
            <button className="tactical-toggle" onClick={() => setView("review")}>[ALT+R] REVIEW</button>
          </div>

          <div className="control-group">
            <div className="control-label">1. BASELINE (PAST) <span className="mono">[ALT+B]</span></div>
            {dropzone("file-a", "Baseline", fileA, setFileA)}
          </div>

          <div className="control-group">
            <div className="control-label">2. RECON (CURRENT) <span className="mono">[ALT+C]</span></div>
            {dropzone("file-b", "Recon", fileB, setFileB)}
          </div>

          <div className="control-group">
            <div className="control-label">TARGET CRITERIA (AI)</div>
            <div className="toggle-grid">
              {presets.map((p) => (
                <button
                  key={p.id}
                  className={`tactical-toggle preset-toggle ${criteria.includes(p.id) ? "active" : ""}`}
                  aria-pressed={criteria.includes(p.id)}
                  onClick={() => toggleCriteria(p.id)}
                >
                  <span className="mono">[{p.shortcut.toUpperCase()}]</span> {p.label.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="control-group">
            <div className="control-label">CUSTOM QUERY (OPTIONAL) <span className="mono">[/]</span></div>
            <input
              ref={queryRef}
              type="text"
              className="tactical-input"
              placeholder="e.g. 'destroyed artillery'"
              value={customQuery}
              onChange={(e) => setCustomQuery(e.target.value)}
            />
          </div>

          <div style={{ flexGrow: 1 }} />

          <button
            className={`btn-exec ${loading ? "active" : ""}`}
            onClick={handleExecute}
            disabled={loading || !fileA || !fileB || (!criteria.length && !customQuery.trim())}
            style={loading ? { background: "var(--accent-active)", color: "var(--accent-active-text)", borderColor: "var(--accent-active)" } : {}}
          >
            <span>{loading ? `[PROCESSING...]` : "EXECUTE"}</span>
            <span className="shortcut-key">[F5] / [CTRL+ENTER]</span>
          </button>
        </div>
      </aside>

      {/* CENTER PANE: THE DIFF ENGINE */}
      <main className="pane">
        <div className="pane-header">
          <div className="pane-title">DIFF ENGINE // WORKSPACE</div>
          {data && (
             <div className="fs-xs mono">
               TARGETS FOUND: {data.result.changes.length}
             </div>
          )}
        </div>

        <div className="pane-content" style={{ padding: 0 }}>
          {loading ? (
            <div className="wireframe-placeholder">
              <div>PROCESSING...</div>
              <div className="fs-xs mono">STAGE: {stage}</div>
            </div>
          ) : data ? (
            <ResultViewer
              data={data}
              selectedIndex={selectedChangeIdx}
              onSelectIndex={setSelectedChangeIdx}
            />
          ) : (
            <div className="wireframe-placeholder">
              <div className="wireframe-grid"></div>
              <div>{error ? <span className="text-danger">EXECUTION FAILED: SEE SYSTEM LOGS</span> : "AWAITING SENSOR INGESTION"}</div>
            </div>
          )}
        </div>
      </main>

      {/* RIGHT PANE: TELEMETRY & OUTPUT */}
      <aside className="pane">
        <div className="pane-header">
          <div className="pane-title">TELEMETRY // OUTPUT</div>
          <div className="header-actions">
            <button className={`header-btn ${theme === "light" ? "active" : ""}`} onClick={toggleLight}>
              [ALT+S] {theme === "light" ? "DARK" : "LIGHT"}
            </button>
            <button className={`header-btn ${theme === "nvg" ? "active" : ""}`} onClick={toggleNvg}>
              [ALT+N] NVG
            </button>
          </div>
        </div>

        <div className="pane-content">
          <div className="control-group">
            <div className="control-label">COORDINATE READOUT</div>
            <div className="log-container" style={{ minHeight: "80px", flexGrow: 0 }}>
              {selectedChangeIdx !== null && data ? (
                <>
                  <div className="log-entry">
                    <span className="log-time">TRGT-ID:</span>
                    <span>TRGT-{String(selectedChangeIdx + 1).padStart(2, '0')}</span>
                  </div>
                  <div className="log-entry">
                    <span className="log-time">BOUNDS:</span>
                    <span>[{data.result.changes[selectedChangeIdx].box.map(Math.round).join(', ')}]</span>
                  </div>
                </>
              ) : (
                <>
                  <div className="log-entry">
                    <span className="log-time">LAT/LON:</span>
                    <span>UNKNOWN (NO GPS)</span>
                  </div>
                  <div className="log-entry">
                    <span className="log-time">BOUNDING:</span>
                    <span>[0-1000] RELATIVE</span>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="control-group" style={{ flexGrow: 1 }}>
            <div className="control-label">SYSTEM LOGS</div>
            <div className="log-container">
              {logs.map((l, i) => {
                 const isWarn = l.includes("[WARN]") || l.includes("[ERR]");
                 const isSuccess = l.includes("[SUCCESS]");
                 return (
                   <div key={i} className={`log-entry ${isWarn ? "text-danger" : isSuccess ? "text-success" : ""}`}>
                     <span className="log-time">{l.split(' ')[0]}</span>
                     <span>{l.split(' ').slice(1).join(' ')}</span>
                   </div>
                 );
              })}
              <div ref={logsEndRef} />
            </div>
          </div>

          <div className="control-group">
            <div className="control-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>EXPORT PIPELINE</span>
              <button className={`header-btn ${inspectorVisible ? "active" : ""}`} onClick={() => setInspectorVisible(!inspectorVisible)}>
                [ALT+I] INSPECT
              </button>
            </div>

            {inspectorVisible && data && (
              <div className="inspector-panel">
                {xmlPreview}
              </div>
            )}

            <div style={{ display: "flex", gap: "4px" }}>
              <button
                className="btn-exec btn-compact"
                disabled={!data}
                onClick={handleExportXML}
              >
                [ALT+X] XML (CoT)
              </button>
              <button
                className="btn-exec btn-compact"
                disabled={!data}
                onClick={handleExportJSON}
              >
                [ALT+J] JSON
              </button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
