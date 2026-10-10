import { useEffect, useRef, useState } from "react";
import { analyze, checkHealth, CancelledError, type JobProgress } from "./api";
import type { AnalyzeResponse } from "./types";
import ResultViewer from "./components/ResultViewer";

const HEALTH_INTERVAL_MS = 15000;

export default function App() {
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  
  // Tactical State
  const [fileA, setFileA] = useState<File | null>(null);
  const [fileB, setFileB] = useState<File | null>(null);
  const [criteria, setCriteria] = useState<string[]>(["vehicles"]);
  const [customQuery, setCustomQuery] = useState<string>("");

  const toggleCriteria = (val: string) => {
    setCriteria(prev => 
      prev.includes(val) ? prev.filter(c => c !== val) : [...prev, val]
    );
  };
  const [logs, setLogs] = useState<string[]>(["[SYS] Terminal initialized."]);
  const [selectedChangeIdx, setSelectedChangeIdx] = useState<number | null>(null);
  
  const logsEndRef = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "F5" || (e.ctrlKey && e.key === "Enter")) {
        e.preventDefault();
        handleExecute();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handlePurge();
      } else if (e.altKey && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        document.body.className = "theme-nvg";
        addLog("[SYS] NIGHT VISION (NVG) MODE ENGAGED.");
      } else if (e.altKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        document.body.className = "theme-sun";
        addLog("[SYS] HIGH-CONTRAST DAYLIGHT MODE ENGAGED.");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const handleDropA = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) {
      if (!file.type.startsWith("image/")) {
        addLog(`[ERR] BASELINE INGEST FAILED. INVALID FORMAT.`);
        return;
      }
      setFileA(file);
      addLog(`[INGEST] Baseline loaded: ${file.name}`);
    }
  };

  const handleDropB = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) {
      if (!file.type.startsWith("image/")) {
        addLog(`[ERR] RECON INGEST FAILED. INVALID FORMAT.`);
        return;
      }
      setFileB(file);
      addLog(`[INGEST] Recon loaded: ${file.name}`);
    }
  };

  const handleExecute = async () => {
    if (!fileA || !fileB) {
      addLog("[ERR] Missing imagery for execution.");
      return;
    }
    const myRun = ++runId.current;
    const isCancelled = () => runId.current !== myRun;

    setLoading(true);
    setError(null);
    setData(null);
    setStage("queued");
    addLog("[EXEC] Initiating diff engine sequence...");

    const activeCriteria = customQuery.trim() ? [...criteria, customQuery.trim()] : criteria;
    const criteriaPayload = JSON.stringify(activeCriteria);

    try {
      const response = await analyze(
        fileA, fileB, criteriaPayload, "en", false,
        (progress: JobProgress) => {
          setStage(progress.stage);
          addLog(`[PROC] Stage advanced: ${progress.stage}`);
        },
        isCancelled
      );
      if (isCancelled()) return;
      setData(response);
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
      // Mock CoT type classification based on 'vehicles' string or just default to hostile ground 'a-h-G'
      const cotType = criteria.some(c => c.toLowerCase().includes("vehicle")) ? "a-h-G-U-C" : "a-h-G";
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
          <div className="control-group">
            <div className="control-label">1. BASELINE (PAST)</div>
            <div 
              className="tactical-dropzone" 
              onDragOver={e => e.preventDefault()} 
              onDrop={handleDropA}
              onClick={() => document.getElementById("file-a")?.click()}
            >
              <span className="dropzone-label">{fileA ? fileA.name : "DRAG & DROP OR CLICK"}</span>
              <input type="file" id="file-a" hidden onChange={e => {
                if (e.target.files?.[0]) {
                  setFileA(e.target.files[0]);
                  addLog(`[INGEST] Baseline: ${e.target.files[0].name}`);
                }
              }} />
            </div>
          </div>

          <div className="control-group">
            <div className="control-label">2. RECON (CURRENT)</div>
            <div 
              className="tactical-dropzone" 
              onDragOver={e => e.preventDefault()} 
              onDrop={handleDropB}
              onClick={() => document.getElementById("file-b")?.click()}
            >
              <span className="dropzone-label">{fileB ? fileB.name : "DRAG & DROP OR CLICK"}</span>
              <input type="file" id="file-b" hidden onChange={e => {
                if (e.target.files?.[0]) {
                  setFileB(e.target.files[0]);
                  addLog(`[INGEST] Recon: ${e.target.files[0].name}`);
                }
              }} />
            </div>
          </div>

          <div className="control-group" style={{ marginTop: "16px" }}>
            <div className="control-label">TARGET CRITERIA</div>
            <div className="toggle-grid">
              <button 
                className={`tactical-toggle ${criteria.includes("vehicles") ? "active" : ""}`}
                onClick={() => toggleCriteria("vehicles")}
              >
                VEHICLES
              </button>
              <button 
                className={`tactical-toggle ${criteria.includes("craters") ? "active" : ""}`}
                onClick={() => toggleCriteria("craters")}
              >
                CRATERS
              </button>
              <button 
                className={`tactical-toggle ${criteria.includes("felled trees") ? "active" : ""}`}
                onClick={() => toggleCriteria("felled trees")}
              >
                TRENCHES / TREES
              </button>
              <button 
                className={`tactical-toggle ${criteria.includes("buildings") ? "active" : ""}`}
                onClick={() => toggleCriteria("buildings")}
              >
                STRUCTURES
              </button>
            </div>
          </div>

          <div className="control-group" style={{ marginTop: "16px" }}>
            <div className="control-label">CUSTOM QUERY (OPTIONAL)</div>
            <input 
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
            disabled={loading || !fileA || !fileB}
            style={loading ? { background: "var(--accent-active)", color: "var(--accent-active-text)", borderColor: "var(--accent-active)" } : {}}
          >
            <span>{loading ? `[PROCESSING...]` : "EXECUTE"}</span>
            <span className="shortcut-key" style={loading ? { borderColor: "var(--accent-active-text)" } : {}}>[F5] / [CTRL+ENTER]</span>
          </button>
        </div>
      </aside>

      {/* CENTER PANE: THE DIFF ENGINE */}
      <main className="pane">
        <div className="pane-header">
          <div className="pane-title">DIFF ENGINE // WORKSPACE</div>
          {data && (
             <div className="fs-xs mono text-warn">
               TARGETS FOUND: {data.result.changes.length}
             </div>
          )}
        </div>
        
        <div className="pane-content" style={{ padding: 0 }}>
          {loading ? (
            <div className="wireframe-placeholder text-warn">
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
              <div>AWAITING SENSOR INGESTION</div>
            </div>
          )}
        </div>
      </main>

      {/* RIGHT PANE: TELEMETRY & OUTPUT */}
      <aside className="pane">
        <div className="pane-header">
          <div className="pane-title">TELEMETRY // OUTPUT</div>
          <div className="fs-xs mono text-dim">REC: ON</div>
        </div>
        
        <div className="pane-content">
          <div className="control-group">
            <div className="control-label">COORDINATE READOUT</div>
            <div className="log-container" style={{ minHeight: "80px", flexGrow: 0 }}>
              {selectedChangeIdx !== null && data ? (
                <>
                  <div className="log-entry">
                    <span className="log-time">TRGT-ID:</span>
                    <span className="text-warn">TRGT-{String(selectedChangeIdx + 1).padStart(2, '0')}</span>
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

          <div className="control-group" style={{ flexGrow: 1, marginTop: "8px" }}>
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

          <div className="control-group" style={{ marginTop: "16px" }}>
            <div className="control-label" style={{ display: "flex", justifyContent: "space-between" }}>
              <span>EXPORT PIPELINE</span>
              <span 
                style={{ cursor: "pointer", color: inspectorVisible ? "var(--accent-exec)" : "var(--text-dim)" }} 
                onClick={() => setInspectorVisible(!inspectorVisible)}
              >
                [INSPECT]
              </span>
            </div>

            {inspectorVisible && data && (
              <div className="inspector-panel">
                {xmlPreview}
              </div>
            )}

            <div style={{ display: "flex", gap: "4px" }}>
              <button 
                className="btn-exec" 
                style={{ flex: 1, padding: "8px", fontSize: "12px" }} 
                disabled={!data} 
                onClick={handleExportXML}
              >
                XML (CoT)
              </button>
              <button 
                className="btn-exec" 
                style={{ flex: 1, padding: "8px", fontSize: "12px" }} 
                disabled={!data} 
                onClick={handleExportJSON}
              >
                JSON
              </button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
