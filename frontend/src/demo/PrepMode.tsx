import { useEffect, useRef, useState } from "react";
import { analyze, CancelledError, fetchPresets, type JobProgress, type Preset } from "../api";
import ResultViewer from "../components/ResultViewer";
import { CATEGORY_LABELS, type AnalyzeResponse } from "../types";
import { errorText, isTyping, pad2, targetId } from "../util";
import {
  cacheScene,
  deleteScene,
  fetchSamples,
  fetchScenes,
  fetchStatus,
  fileFromUrl,
  renameScene,
  reorderScenes,
  sourceUrl,
  type DemoStatus,
  type Sample,
} from "./prepApi";
import { sceneFile, type DemoScene } from "./scene";

// Prep mode (admin only, docs/demo.md). Run a pair through the AI, review the boxes and labels, re-prompt or swap
// images and run again; CACHE STATE then freezes the run (exact images + AI JSON) into demo_cache, which is all the
// presentation view reads. Reuses the operator terminal's analysis client and ResultViewer unchanged.

type Lang = "en" | "lt";

/** One finished run: what was sent and what came back. CACHE STATE always stores this, never later edits. */
interface Run {
  jobId: string;
  fileA: File;
  fileB: File;
  presets: string[];
  query: string;
  lang: Lang;
  response: AnalyzeResponse;
  cachedAs: string | null; // scene id once cached
}

/** Where a run's detections came from, read from the job warnings (same rule as backend store.result_source). */
function runSource(warnings: string[] = []): DemoScene["source"] {
  if (warnings.some((w) => w.startsWith("AI step disabled"))) return "ai_off";
  if (warnings.some((w) => w.startsWith("OFFLINE MODE"))) return "fixtures";
  return "gemini";
}

/** A cached scene in the shape ResultViewer renders (no heatmap: it is not cached). */
function sceneResponse(scene: DemoScene): AnalyzeResponse {
  return {
    job_id: scene.source_job,
    result: scene.result,
    align_quality: scene.align.quality,
    align_ok: scene.align.ok,
    images: {
      image_a_url: sceneFile(scene, "image_a"),
      aligned_b_url: sceneFile(scene, "aligned_b"),
      annotated_url: sceneFile(scene, "annotated"),
    },
    warnings: scene.warnings,
  };
}

const sameSet = (a: string[], b: string[]) => [...a].sort().join() === [...b].sort().join();

export default function PrepMode() {
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [scenes, setScenes] = useState<DemoScene[]>([]);

  // Editor: what the next run sends.
  const [fileA, setFileA] = useState<File | null>(null);
  const [fileB, setFileB] = useState<File | null>(null);
  const [dragTarget, setDragTarget] = useState<string | null>(null);
  const [criteria, setCriteria] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [lang, setLang] = useState<Lang>("en");
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null); // cached scene that CACHE STATE replaces

  // Review: the last run, or a cached scene loaded for editing.
  const [run, setRun] = useState<Run | null>(null);
  const [shown, setShown] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState("");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [busy, setBusy] = useState(false); // a cache action is in flight
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  const runId = useRef(0);
  const queryRef = useRef<HTMLInputElement>(null);

  const say = (text: string, error = false) => setMessage({ text, error });
  const fail = (e: unknown) => say(errorText(e), true);
  const refreshScenes = () => fetchScenes().then(setScenes).catch(fail);

  useEffect(() => {
    fetchStatus().then(setStatus).catch(fail);
    fetchPresets().then(setPresets).catch(fail);
    fetchSamples().then(setSamples).catch(() => setSamples([]));
    refreshScenes();
  }, []);

  const changes = shown?.result.changes ?? [];
  const selected = selectedIdx !== null ? changes[selectedIdx] ?? null : null;
  const editing = scenes.find((s) => s.id === editingId) ?? null;
  const showingRun = !!run && shown === run.response;
  const source = showingRun ? runSource(run.response.warnings) : null;
  const stale =
    !!run &&
    (run.fileA !== fileA || run.fileB !== fileB || run.query !== query.trim() || run.lang !== lang ||
      !sameSet(run.presets, criteria));

  const toggleCriteria = (id: string) =>
    setCriteria((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));

  const ingest = (file: File | undefined, set: (f: File) => void) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) return say(`${file.name} is not an image.`, true);
    set(file);
  };

  const handleRun = async () => {
    if (!fileA || !fileB) return say("Pick a baseline and a recon image first.", true);
    const q = query.trim();
    if (!criteria.length && !q) return say("Select a target class or type a prompt.", true);
    const myRun = ++runId.current;
    const isCancelled = () => runId.current !== myRun;
    const inputs = { fileA, fileB, presets: [...criteria], query: q, lang };

    setLoading(true);
    setStage("queued");
    setSelectedIdx(null);
    say(`Running AI: ${fileA.name} vs ${fileB.name}`);
    try {
      const response = await analyze(
        fileA, fileB, { presets: inputs.presets, query: q }, lang, false,
        (p: JobProgress) => setStage(p.stage),
        isCancelled
      );
      if (isCancelled()) return;
      setRun({ ...inputs, jobId: response.job_id, response, cachedAs: null });
      setShown(response);
      say(`${response.result.changes.length} detection(s). Review them, then CACHE STATE, or re-prompt and run again.`);
    } catch (e) {
      if (e instanceof CancelledError || isCancelled()) return;
      fail(e);
    } finally {
      if (!isCancelled()) {
        setLoading(false);
        setStage("");
      }
    }
  };

  const handleCache = async () => {
    if (busy || loading) return;
    if (!run) return say("Run the AI first: CACHE STATE stores a finished run.", true);
    if (run.cachedAs) return say("This run is already cached. Change the prompt or images and run again.", true);
    if (!title.trim()) return say("Give the scene a title: the audience sees it.", true);
    const src = runSource(run.response.warnings);
    if (
      src !== "gemini" &&
      !window.confirm(
        src === "fixtures"
          ? "This run used OFFLINE FIXTURES, not the Gemini model. Cache it anyway?"
          : "The AI step was OFF for this run, so it has no detections. Cache it anyway?"
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      const scene = await cacheScene(run.jobId, title.trim(), subtitle.trim(), { a: run.fileA, b: run.fileB }, editingId);
      setRun({ ...run, cachedAs: scene.id });
      await refreshScenes();
      say(`${editingId ? "Updated" : "Cached"} scene "${scene.title}": ${scene.result.changes.length} target(s).`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const newScene = () => {
    runId.current++; // drop a run in flight
    setLoading(false);
    setStage("");
    setEditingId(null);
    setRun(null);
    setShown(null);
    setSelectedIdx(null);
    setFileA(null);
    setFileB(null);
    setTitle("");
    setSubtitle("");
    say("New scene: pick a pair, set the prompt, run the AI.");
  };

  const loadScene = async (scene: DemoScene) => {
    runId.current++;
    setLoading(false);
    setStage("");
    setEditingId(scene.id);
    setRun(null);
    setShown(sceneResponse(scene));
    setSelectedIdx(null);
    setTitle(scene.title);
    setSubtitle(scene.subtitle);
    setCriteria(scene.presets);
    setQuery(scene.query);
    setLang(scene.lang === "lt" ? "lt" : "en");
    const a = sourceUrl(scene, "source_a");
    const b = sourceUrl(scene, "source_b");
    if (!a || !b) {
      setFileA(null);
      setFileB(null);
      return say(`Loaded "${scene.title}" without its original images: pick them again before running.`, true);
    }
    try {
      const [fa, fb] = await Promise.all([fileFromUrl(a, scene.files.source_a!), fileFromUrl(b, scene.files.source_b!)]);
      setFileA(fa);
      setFileB(fb);
      say(`Editing "${scene.title}": re-prompt or swap images, run the AI, then UPDATE SCENE.`);
    } catch (e) {
      fail(e);
    }
  };

  const moveScene = async (i: number, step: number) => {
    const j = i + step;
    if (j < 0 || j >= scenes.length) return;
    const ids = scenes.map((s) => s.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try {
      await reorderScenes(ids);
      await refreshScenes();
    } catch (e) {
      fail(e);
    }
  };

  const renameCached = async (scene: DemoScene) => {
    const t = window.prompt("Scene title (shown to the audience)", scene.title);
    if (t === null) return;
    const s = window.prompt("Subtitle (optional)", scene.subtitle);
    if (s === null) return;
    try {
      const renamed = await renameScene(scene.id, t, s);
      if (editingId === scene.id) {
        setTitle(renamed.title);
        setSubtitle(renamed.subtitle);
      }
      await refreshScenes();
    } catch (e) {
      fail(e);
    }
  };

  const removeScene = async (scene: DemoScene) => {
    if (!window.confirm(`Delete cached scene "${scene.title}"? Its images and AI output leave demo_cache.`)) return;
    try {
      await deleteScene(scene.id);
      if (editingId === scene.id) setEditingId(null);
      await refreshScenes();
      say(`Deleted scene "${scene.title}".`);
    } catch (e) {
      fail(e);
    }
  };

  const loadSample = async (sample: Sample) => {
    try {
      const [a, b] = await Promise.all([
        fileFromUrl(sample.image_a_url, `${sample.id}_a.jpg`),
        fileFromUrl(sample.image_b_url, `${sample.id}_b.jpg`),
      ]);
      setFileA(a);
      setFileB(b);
      if (!title.trim()) setTitle(sample.name);
      say(`Sample ${sample.id} loaded: ${sample.description}`);
    } catch (e) {
      fail(e);
    }
  };

  const launchPresentation = () => window.open("/demo.html", "zvalgas-presentation");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (e.key === "F5" || (e.ctrlKey && e.key === "Enter")) {
        e.preventDefault();
        if (!loading) handleRun();
      } else if (e.ctrlKey && key === "s") {
        e.preventDefault();
        handleCache();
      } else if (e.altKey && key === "p") {
        e.preventDefault();
        launchPresentation();
      } else if (e.altKey && key === "n") {
        e.preventDefault();
        newScene();
      } else if (e.altKey && key === "b") {
        e.preventDefault();
        document.getElementById("prep-a")?.click();
      } else if (e.altKey && key === "c") {
        e.preventDefault();
        document.getElementById("prep-b")?.click();
      } else if (e.altKey && /^Digit[1-9]$/.test(e.code)) {
        const preset = presets[Number(e.code.slice(5)) - 1];
        if (!preset) return;
        e.preventDefault();
        toggleCriteria(preset.id);
      } else if (e.key === "/" && !isTyping(e.target)) {
        e.preventDefault();
        queryRef.current?.focus();
      } else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && changes.length && !isTyping(e.target)) {
        e.preventDefault();
        const step = e.key === "ArrowUp" ? -1 : 1;
        setSelectedIdx((i) => (i === null ? 0 : Math.max(0, Math.min(changes.length - 1, i + step))));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const dropzone = (id: string, file: File | null, set: (f: File) => void) => (
    <div
      className={`tactical-dropzone ${dragTarget === id ? "dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (dragTarget !== id) setDragTarget(id);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragTarget(null);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragTarget(null);
        ingest(e.dataTransfer.files?.[0], set);
      }}
      onClick={() => document.getElementById(id)?.click()}
    >
      <span className="dropzone-label">{file ? file.name : "DRAG & DROP OR CLICK"}</span>
      <input
        type="file"
        id={id}
        accept="image/*"
        hidden
        onChange={(e) => {
          ingest(e.target.files?.[0], set);
          e.target.value = "";
        }}
      />
    </div>
  );

  const statusText = !status
    ? "AI: ..."
    : !status.ai_enabled
      ? "AI: OFF"
      : status.live
        ? `AI: LIVE ${status.model.toUpperCase()}`
        : "AI: OFFLINE FIXTURES";
  const statusClass = !status ? "text-dim" : status.ai_enabled && status.live ? "text-success" : "text-danger";

  const cacheLabel = run?.cachedAs ? "CACHED ✓" : editingId ? "UPDATE SCENE" : "CACHE STATE";

  return (
    <div className="terminal-layout">
      {/* LEFT: what the AI gets */}
      <aside className="pane">
        <div className="pane-header">
          <div className="pane-title text-success">ŽVALGAS // DEMO PREP</div>
          <div className={`fs-xs mono ${statusClass}`}>{statusText}</div>
        </div>

        <div className="pane-content">
          <div className="control-group">
            <div className="control-label">1. BASELINE (PAST) <span className="mono">[ALT+B]</span></div>
            {dropzone("prep-a", fileA, setFileA)}
          </div>

          <div className="control-group">
            <div className="control-label">2. RECON (CURRENT) <span className="mono">[ALT+C]</span></div>
            {dropzone("prep-b", fileB, setFileB)}
          </div>

          {samples.length > 0 && (
            <div className="control-group">
              <div className="control-label">SAMPLE PAIRS</div>
              <div className="toggle-grid">
                {samples.map((s) => (
                  <button key={s.id} className="tactical-toggle" title={s.name} onClick={() => loadSample(s)}>
                    {s.id.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          )}

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
            <div className="control-label">PROMPT / CUSTOM QUERY <span className="mono">[/]</span></div>
            <input
              ref={queryRef}
              type="text"
              className="tactical-input"
              placeholder="e.g. 'fresh craters along the treeline'"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="control-group">
            <div className="control-label">REPORT LANGUAGE</div>
            <div className="toggle-grid">
              {(["en", "lt"] as const).map((l) => (
                <button key={l} className={`tactical-toggle ${lang === l ? "active" : ""}`} onClick={() => setLang(l)}>
                  {l.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="spacer" />

          {status?.answer_cache && (
            <div className="fs-xs mono text-dim">
              ANSWER CACHE ON: AN IDENTICAL RE-RUN RETURNS THE STORED ANSWER. START WITH demo.ps1 prep FOR FRESH RUNS.
            </div>
          )}

          <button
            className={`btn-exec ${loading ? "active" : ""}`}
            onClick={handleRun}
            disabled={loading || !fileA || !fileB || (!criteria.length && !query.trim())}
          >
            <span>{loading ? "[PROCESSING...]" : run || editing ? "RE-RUN AI" : "RUN AI"}</span>
            <span className="shortcut-key">[F5]</span>
          </button>
        </div>
      </aside>

      {/* CENTER: the AI's boxes on the pair */}
      <main className="pane">
        <div className="pane-header">
          <div className="pane-title">
            REVIEW // {showingRun ? `RUN ${run.jobId}` : editing ? `CACHED: ${editing.title}` : "AI DETECTIONS"}
          </div>
          {shown && <div className="fs-xs mono">TARGETS: {changes.length}</div>}
        </div>

        <div className="pane-content flush">
          {loading ? (
            <div className="wireframe-placeholder">
              <div>PROCESSING...</div>
              <div className="fs-xs mono">STAGE: {stage === "ai" ? "ANALYZING DATA" : stage}</div>
            </div>
          ) : shown ? (
            <ResultViewer data={shown} selectedIndex={selectedIdx} onSelectIndex={setSelectedIdx} />
          ) : (
            <div className="wireframe-placeholder">
              <div className="wireframe-grid"></div>
              <div>PICK A PAIR, SET THE PROMPT, [F5] RUN AI</div>
            </div>
          )}
        </div>
      </main>

      {/* RIGHT: verdict, cache, presentation */}
      <aside className="pane">
        <div className="pane-header">
          <div className="pane-title">CACHE // PRESENT</div>
          <div className="header-actions">
            <button className="header-btn" onClick={launchPresentation}>[ALT+P] LAUNCH PRESENTATION</button>
          </div>
        </div>

        <div className="pane-content">
          {message && <div className={`fs-xs mono ${message.error ? "text-danger" : "text-dim"}`}>{message.text}</div>}

          {source && source !== "gemini" && (
            <div className="prep-banner">
              {source === "fixtures"
                ? "THIS RUN CAME FROM OFFLINE FIXTURES, NOT GEMINI. CHECK GEMINI_API_KEY AND THE WARNINGS BELOW."
                : "THE AI STEP WAS OFF FOR THIS RUN: NO DETECTIONS."}
            </div>
          )}
          {stale && (
            <div className="prep-banner dim">INPUTS CHANGED SINCE THE LAST RUN. CACHE STATE STORES THE LAST RUN: [F5] TO RE-RUN.</div>
          )}

          {shown && (
            <>
              <div className="control-group">
                <div className="control-label split">
                  <span>DETECTIONS <span className="mono">[↑/↓]</span></span>
                  <span className="mono">{changes.length}</span>
                </div>
                {changes.length ? (
                  <div className="target-list">
                    {changes.map((c, i) => (
                      <button
                        key={i}
                        className={`target-row ${selectedIdx === i ? "active" : ""}`}
                        title={c.description}
                        onClick={() => setSelectedIdx(selectedIdx === i ? null : i)}
                      >
                        <span className="mono">{targetId(i)}</span>
                        <span className="target-row-label">{c.type}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="fs-xs mono text-dim">NO DETECTIONS. RE-PROMPT OR SWAP IMAGES.</div>
                )}
              </div>

              {selected && selectedIdx !== null && (
                <div className="log-container readout">
                  <div className="log-entry"><span className="log-time">TRGT-ID:</span><span>{targetId(selectedIdx)}</span></div>
                  <div className="log-entry"><span className="log-time">LABEL:</span><span>{selected.type}</span></div>
                  <div className="log-entry"><span className="log-time">CONF:</span><span>{selected.confidence.toUpperCase()}</span></div>
                  <div className="log-entry">
                    <span className="log-time">CLASS:</span>
                    <span>{selected.category ? CATEGORY_LABELS[selected.category] : "-"}</span>
                  </div>
                  <div className="log-entry"><span className="log-time">SECTOR:</span><span>{selected.sector ?? "-"}</span></div>
                  <div className="log-entry"><span className="log-time">DESC:</span><span>{selected.description}</span></div>
                  <div className="log-entry"><span className="log-time">WHERE:</span><span>{selected.location_text || "-"}</span></div>
                </div>
              )}

              <div className="control-group">
                <div className="control-label">SUMMARY</div>
                <div className="fs-xs">{shown.result.summary}</div>
                <div className="control-label">RECOMMENDATION</div>
                <div className="fs-xs">{shown.result.recommendation}</div>
              </div>

              {!!shown.warnings?.length && (
                <div className="control-group">
                  <div className="control-label">WARNINGS (NOT SHOWN TO THE AUDIENCE)</div>
                  {shown.warnings.map((w, i) => (
                    <div key={i} className="fs-xs mono text-danger">{w}</div>
                  ))}
                </div>
              )}
            </>
          )}

          <div className="control-group">
            <div className="control-label split">
              <span className="prep-ellipsis" title={editing?.title}>
                {editing ? `SCENE: EDITING "${editing.title}"` : "SCENE: NEW"}
              </span>
              <button className="header-btn prep-nowrap" onClick={newScene}>[ALT+N] NEW</button>
            </div>
            <input
              type="text"
              className="tactical-input"
              placeholder="Title shown to the audience"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <input
              type="text"
              className="tactical-input"
              placeholder="Subtitle (optional)"
              value={subtitle}
              onChange={(e) => setSubtitle(e.target.value)}
            />
            <button
              className={`btn-exec btn-compact ${busy ? "active" : ""}`}
              onClick={handleCache}
              disabled={busy || loading || !run || !!run.cachedAs || !title.trim()}
            >
              [CTRL+S] {busy ? "CACHING..." : cacheLabel}
            </button>
          </div>

          <div className="control-group">
            <div className="control-label split">
              <span>CACHED SCENES (PRESENTATION ORDER)</span>
              <span className="mono">{scenes.length}</span>
            </div>
            {!scenes.length && <div className="fs-xs mono text-dim">NOTHING CACHED YET.</div>}
            {scenes.map((s, i) => (
              <div key={s.id} className={`scene-row ${s.id === editingId ? "editing" : ""}`}>
                <span className="mono">{pad2(i + 1)}</span>
                <img className="scene-thumb" src={sceneFile(s, "aligned_b")} alt="" />
                <span className="scene-row-title" title={`${s.title}${s.subtitle ? ` — ${s.subtitle}` : ""}`}>
                  {s.title}
                  <span className="text-dim mono">
                    {" "}· {s.result.changes.length} TRGT{s.source !== "gemini" ? ` · ${s.source.toUpperCase()}` : ""}
                  </span>
                </span>
                <span className="scene-actions">
                  <button className="header-btn" title="Move up" disabled={i === 0} onClick={() => moveScene(i, -1)}>▲</button>
                  <button className="header-btn" title="Move down" disabled={i === scenes.length - 1} onClick={() => moveScene(i, 1)}>▼</button>
                  <button className="header-btn" title="Load into the editor to re-run" onClick={() => loadScene(s)}>LOAD</button>
                  <button className="header-btn" title="Rename" onClick={() => renameCached(s)}>REN</button>
                  <button className="header-btn" title="Delete" onClick={() => removeScene(s)}>DEL</button>
                </span>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </div>
  );
}
