import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  batchPair,
  clearQueue,
  fetchBatch,
  fetchBatches,
  fetchInbox,
  fetchPresets,
  fetchSettings,
  rerunBatch,
  reportUrl,
  reviewFinding,
  updateSettings,
  type Batch,
  type BatchDetail,
  type FramePair,
  type InboxPair,
  type InboxState,
  type PipelineSettings,
  type Preset,
  type ReportFormat,
  type ReviewStatus,
} from "../api";
import { CATEGORY_LABELS, CATEGORY_ORDER, type AlignMethod, type AnalyzeResponse } from "../types";
import ReportViewer from "./ReportViewer";
import ResultViewer from "./ResultViewer";

const POLL_MS = 3000;

const pad2 = (n: number) => String(n).padStart(2, "0");
const clock = (t: number) => `${pad2(Math.floor(t / 60))}:${pad2(Math.floor(t % 60))}`;
const pct = (v: number | null | undefined) => `${Math.round((v ?? 0) * 100)}%`;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// A matched frame pair in the shape ResultViewer already renders (slider / HUD / split / heatmap).
function pairResponse(batch: BatchDetail, pair: FramePair): AnalyzeResponse {
  const method = pair.align_method;
  return {
    job_id: pair.id,
    result: {
      report_date: batch.created_at.slice(0, 10),
      summary: pair.summary,
      recommendation: pair.recommendation,
      changes: pair.findings.map((f) => ({
        type: f.type,
        description: f.description,
        location_text: f.location_text,
        confidence: f.confidence,
        box: f.box,
        sector: f.sector,
        category: f.category,
      })),
    },
    align_quality: pair.align_quality,
    align_ok: true,
    align_method: method === "sift" || method === "ecc" ? (method as AlignMethod) : "none",
    images: pair.images,
  };
}

const pairKey = (p: InboxPair) => `${p.name_a}|${p.name_b}`;

function batchState(b: Batch): { text: string; cls: string } {
  if (b.status === "done") return { text: "DONE", cls: "text-success" };
  if (b.status === "error") return { text: "ERROR", cls: "text-danger" };
  if (b.status === "running") return { text: `${b.stage.toUpperCase()} ${b.progress}`.trim(), cls: "text-warn" };
  return { text: "QUEUED", cls: "text-dim" };
}

interface Props {
  onExit: () => void;
}

export default function ReviewDashboard({ onExit }: Props) {
  const [settings, setSettings] = useState<PipelineSettings | null>(null);
  const [inbox, setInbox] = useState<InboxState | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [pairIdx, setPairIdx] = useState(0);
  const [findingIdx, setFindingIdx] = useState<number | null>(null);
  const [statusLine, setStatusLine] = useState("[SYS] Review terminal online.");
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  // Pairs batched by hand that the inbox poll does not show as batched yet.
  const [pendingPairs, setPendingPairs] = useState<Set<string>>(() => new Set());
  // Target classes for new batches; the query is committed on Enter or blur, not per keystroke.
  const [presets, setPresets] = useState<Preset[]>([]);
  const [queryDraft, setQueryDraft] = useState("");
  const queryFocused = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [s, i, list] = await Promise.all([fetchSettings(), fetchInbox(), fetchBatches()]);
      setSettings(s);
      setInbox(i);
      setBatches(list);
      setBackendUp(true);
    } catch (e: any) {
      setBackendUp(false);
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (!selectedId && batches.length) setSelectedId(batches[0].id);
  }, [batches, selectedId]);

  useEffect(() => {
    fetchPresets()
      .then(setPresets)
      .catch((e) => setStatusLine(`[ERR] TARGET CLASSES UNAVAILABLE: ${e?.message || String(e)}`));
  }, []);

  const savedQuery = settings?.batch_query ?? "";
  useEffect(() => {
    if (!queryFocused.current) setQueryDraft(savedQuery);
  }, [savedQuery]);

  // A pending pair is settled once the poll reports it batched (or it left the inbox).
  useEffect(() => {
    if (!inbox || !pendingPairs.size) return;
    const open = new Set(inbox.pairs.filter((p) => !p.batched).map(pairKey));
    setPendingPairs((prev) => {
      const next = new Set([...prev].filter((k) => open.has(k)));
      return next.size === prev.size ? prev : next;
    });
  }, [inbox]);

  // Reload the selected batch when it is picked or its row changes (stage, progress, finish).
  const row = batches.find((b) => b.id === selectedId) ?? null;
  const rowStamp = row ? `${row.updated_at}|${row.status}|${row.progress}` : "";
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let alive = true;
    fetchBatch(selectedId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setStatusLine(`[ERR] ${e?.message || String(e)}`));
    return () => {
      alive = false;
    };
  }, [selectedId, rowStamp]);

  useEffect(() => {
    setPairIdx(0);
    setReportOpen(false);
  }, [selectedId]);

  const shown = detail && detail.id === selectedId ? detail : null;
  const pairs = shown ? shown.pairs : [];
  const pair = pairs.length ? pairs[clamp(pairIdx, 0, pairs.length - 1)] : null;

  // Findings in display order: grouped by category, then by number.
  const order = useMemo(() => {
    if (!pair) return [];
    const rank = (i: number) => CATEGORY_ORDER.indexOf(pair.findings[i].category);
    return pair.findings.map((_, i) => i).sort((x, y) => rank(x) - rank(y) || x - y);
  }, [pair]);

  useEffect(() => {
    setFindingIdx(order.length ? order[0] : null);
  }, [pair?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (findingIdx !== null) document.getElementById(`finding-${findingIdx}`)?.scrollIntoView({ block: "nearest" });
  }, [findingIdx]);

  const review = async (status: ReviewStatus, index: number | null = findingIdx) => {
    if (!pair || index === null || !pair.findings[index]) return;
    try {
      const updated = await reviewFinding(pair.findings[index].id, status);
      setDetail((d) =>
        d && {
          ...d,
          pairs: d.pairs.map((p) =>
            p.id !== pair.id ? p : { ...p, findings: p.findings.map((f) => (f.id === updated.id ? updated : f)) }
          ),
        }
      );
      setStatusLine(`[REVIEW] TRGT-${pad2(index + 1)} ${status.toUpperCase()}`);
      const pos = order.indexOf(index);
      if (status !== "pending" && pos >= 0 && pos < order.length - 1) setFindingIdx(order[pos + 1]);
      refresh();
    } catch (e: any) {
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  };

  const toggleAi = async () => {
    if (!settings) return;
    try {
      const s = await updateSettings({ ai_enabled: !settings.ai_enabled });
      setSettings(s);
      setStatusLine(`[SYS] AI STEP ${s.ai_enabled ? "ON" : "OFF"} FOR NEW BATCHES.`);
    } catch (e: any) {
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  };

  const toggleAutoBatch = async () => {
    if (!settings) return;
    try {
      const s = await updateSettings({ auto_batch: !settings.auto_batch });
      setSettings(s);
      setStatusLine(
        s.auto_batch
          ? "[SYS] AUTO-BATCHING STARTED: INBOX PROJECTS QUEUED, WORKER RESUMED."
          : "[SYS] AUTO-BATCHING STOPPED: NEW FILES STAY IN THE INBOX, WORKER PAUSED."
      );
      await refresh();
    } catch (e: any) {
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  };

  const saveTarget = async (patch: { batch_presets?: string[]; batch_query?: string }) => {
    try {
      const s = await updateSettings(patch);
      setSettings(s);
      setStatusLine(`[SYS] NEW BATCHES TARGET: ${s.batch_criteria.toUpperCase()}`);
    } catch (e: any) {
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  };

  const toggleTarget = (id: string) => {
    if (!settings) return;
    const ids = settings.batch_presets;
    saveTarget({ batch_presets: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] });
  };

  const commitQuery = () => {
    if (settings && queryDraft.trim() !== settings.batch_query) saveTarget({ batch_query: queryDraft });
  };

  const clearBatchQueue = async () => {
    if (!settings || settings.auto_batch || !settings.queued_count) return;
    const ok = window.confirm(
      `Clear ${settings.queued_count} queued batch(es)? Their files go back to the inbox, unbatched. ` +
        "Finished legs and their reviews are kept."
    );
    if (!ok) return;
    try {
      const r = await clearQueue();
      setStatusLine(`[SYS] QUEUE CLEARED: ${r.deleted.length} BATCH(ES) DROPPED, ${r.files.length} FILE(S) BACK IN INBOX.`);
      if (selectedId && r.deleted.includes(selectedId)) setSelectedId(null);
      await refresh();
    } catch (e: any) {
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  };

  const batchOnePair = async (p: InboxPair) => {
    const key = pairKey(p);
    setPendingPairs((prev) => new Set(prev).add(key));
    try {
      const r = await batchPair(p.name_a, p.name_b);
      setStatusLine(
        r.started
          ? `[EXEC] PAIR ${p.site} ${p.tag_a} → ${p.tag_b} BATCHED BY HAND AS ${r.batch_id}: RUNNING NOW.`
          : `[SYS] PAIR ${p.site} ${p.tag_a} → ${p.tag_b} ADDED TO ITS RUNNING BATCH.`
      );
      if (r.batch_id) setSelectedId(r.batch_id);
      await refresh();
    } catch (e: any) {
      setPendingPairs((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  };

  const requeue = async () => {
    if (!selectedId) return;
    try {
      const id = await rerunBatch(selectedId);
      setStatusLine(`[EXEC] RE-QUEUED AS ${id} (AI ${settings?.ai_enabled ? "ON" : "OFF"}).`);
      await refresh();
      setSelectedId(id);
    } catch (e: any) {
      setStatusLine(`[ERR] ${e?.message || String(e)}`);
    }
  };

  const exportReport = (format: ReportFormat) => {
    if (!selectedId) return;
    const a = document.createElement("a");
    a.href = reportUrl(selectedId, format);
    a.download = `zvalgas_report_${selectedId}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setStatusLine(`[SYS] REPORT EXPORTED (${format.toUpperCase()}): ACCEPTED FINDINGS ONLY.`);
  };

  const moveFinding = (step: number) => {
    if (!order.length) return;
    const pos = findingIdx === null ? -1 : order.indexOf(findingIdx);
    setFindingIdx(order[clamp(pos + step, 0, order.length - 1)]);
  };

  const moveBatch = (step: number) => {
    if (!batches.length) return;
    const pos = batches.findIndex((b) => b.id === selectedId);
    setSelectedId(batches[clamp(pos + step, 0, batches.length - 1)].id);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.getAttribute("role") === "slider")) return;
      if (e.altKey) {
        const key = e.key.toLowerCase();
        if (key === "i") toggleAi();
        else if (key === "b") toggleAutoBatch();
        else if (key === "q") requeue();
        else if (e.key === "ArrowUp") moveBatch(-1);
        else if (e.key === "ArrowDown") moveBatch(1);
        else return;
        e.preventDefault();
        return;
      }
      if (e.ctrlKey || e.metaKey) return;
      const key = e.key.toLowerCase();
      if (reportOpen) {
        // The report is read-only: no triage keys while it covers the pair viewer.
        if (e.key === "Escape" || key === "v") setReportOpen(false);
        else if (key === "e") exportReport("html");
        else if (key === "j") exportReport("json");
        else if (key === "p") exportReport("pdf");
        else return;
        e.preventDefault();
        return;
      }
      if (key === "v" && shown) setReportOpen(true);
      else if (e.key === "ArrowLeft") setPairIdx((i) => clamp(i - 1, 0, Math.max(0, pairs.length - 1)));
      else if (e.key === "ArrowRight") setPairIdx((i) => clamp(i + 1, 0, Math.max(0, pairs.length - 1)));
      else if (e.key === "ArrowUp") moveFinding(-1);
      else if (e.key === "ArrowDown") moveFinding(1);
      else if (key === "a") review("accepted");
      else if (key === "r") review("rejected");
      else if (key === "u") review("pending");
      else if (key === "e") exportReport("html");
      else if (key === "j") exportReport("json");
      else if (key === "p") exportReport("pdf");
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const isStill = (kind: string | null) => kind === "image";
  const timeA = pair ? (isStill(pair.kind_a) ? "STILL" : clock(pair.time_a)) : "";
  const timeB = pair ? (isStill(pair.kind_b) ? "STILL" : clock(pair.time_b)) : "";
  const unbatched = inbox?.groups?.filter((g) => !g.batched) ?? [];

  let center: JSX.Element;
  if (!shown) {
    center = (
      <div className="wireframe-placeholder">
        <div className="wireframe-grid"></div>
        <div>{batches.length ? "LOADING BATCH..." : "NO BATCHES YET"}</div>
        <div className="fs-xs mono">DROP {inbox?.scheme ?? "<key>_<Before|After|DayN>"} FILES INTO</div>
        <div className="fs-xs mono">{settings?.watch_dir ?? "the input folder"}</div>
      </div>
    );
  } else if (shown.status === "error") {
    center = (
      <div className="wireframe-placeholder text-danger">
        <div>[ERR] BATCH FAILED</div>
        <div className="fs-xs mono">{shown.error_message}</div>
      </div>
    );
  } else if (shown.status !== "done") {
    center = (
      <div className="wireframe-placeholder text-warn">
        <div>PROCESSING...</div>
        <div className="fs-xs mono">STAGE: {shown.stage.toUpperCase()} {shown.progress}</div>
      </div>
    );
  } else if (!pair) {
    center = (
      <div className="wireframe-placeholder">
        <div>NO DIFFERENCES FLAGGED</div>
        <div className="fs-xs mono">{shown.matched_pairs ?? 0} MATCHED FRAME PAIRS, NONE WITH CHANGES</div>
      </div>
    );
  } else {
    center = (
      <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <div className="pair-nav">
          <button className="tactical-toggle" disabled={pairIdx <= 0} onClick={() => setPairIdx((i) => Math.max(0, i - 1))}>
            [←] PREV
          </button>
          <div className="pair-nav-info mono">
            <span className="text-warn">PAIR {pad2(pairs.indexOf(pair) + 1)}/{pad2(pairs.length)}</span>
            <span>
              {pair.tag_a}@{timeA} ↔ {pair.tag_b}@{timeB}
            </span>
            <span className="text-dim">
              INL {pair.inliers} · OVL {pct(pair.overlap)} · SSIM {pair.ssim.toFixed(2)} · Δ {pct(pair.change_ratio)} · SRC{" "}
              {pair.source.toUpperCase()}
            </span>
          </div>
          <button
            className="tactical-toggle"
            disabled={pairIdx >= pairs.length - 1}
            onClick={() => setPairIdx((i) => Math.min(pairs.length - 1, i + 1))}
          >
            NEXT [→]
          </button>
        </div>
        <div style={{ position: "relative", flexGrow: 1, minHeight: 0 }}>
          <div style={{ position: "absolute", inset: 0 }}>
            <ResultViewer
              data={pairResponse(shown, pair)}
              selectedIndex={findingIdx}
              onSelectIndex={setFindingIdx}
              statuses={pair.findings.map((f) => f.review_status)}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="terminal-layout">
      {/* LEFT PANE: QUEUE & PIPELINE */}
      <aside className="pane">
        <div className="pane-header">
          <div className="pane-title text-success">ŽVALGAS-SYS // REVIEW</div>
          <div className={`fs-xs mono ${backendUp === false ? "text-danger" : "text-success"}`}>
            {backendUp === false ? "UPLINK: FAIL" : "UPLINK: OK"}
          </div>
        </div>
        <div className="pane-content">
          <div className="toggle-grid">
            <button className="tactical-toggle" onClick={onExit}>[ALT+A] ANALYZE</button>
            <button className="tactical-toggle active">[ALT+R] REVIEW</button>
          </div>

          <div className="control-group">
            <div className="control-label">PIPELINE</div>
            <button className="btn-exec" onClick={toggleAutoBatch} disabled={!settings}>
              <span>AUTO-BATCHING: {settings ? (settings.auto_batch ? "RUNNING" : "STOPPED") : "..."}</span>
              <span className="shortcut-key">[ALT+B]</span>
            </button>
            <div className="fs-xs mono text-dim">
              {settings?.auto_batch
                ? "NEW FILES ARE GROUPED BY PROJECT AND QUEUED"
                : `PAUSED: FILES WAIT IN THE INBOX · ${settings?.queued_count ?? 0} QUEUED`}
            </div>
            {settings && !settings.auto_batch && (
              <button className="tactical-toggle" onClick={clearBatchQueue} disabled={!settings.queued_count}>
                CLEAR BATCH QUEUE ({settings.queued_count})
              </button>
            )}
            <button className={`tactical-toggle ${settings?.ai_enabled ? "active" : ""}`} onClick={toggleAi} disabled={!settings}>
              [ALT+I] AI ANALYSIS: {settings ? (settings.ai_enabled ? "ON" : "OFF") : "..."}
            </button>
            <div className="fs-xs mono text-dim">
              {settings?.ai_enabled && !settings.ai_available
                ? "NO GEMINI KEY / MOCK_LLM=1: BATCHES FALL BACK TO CV"
                : settings?.ai_enabled
                  ? "GEMINI 3.5 FLASH-LITE ON CURATED PAIRS"
                  : "CV ONLY: HEATMAP REGIONS, UNCLASSIFIED"}
            </div>
            <div className="fs-xs mono text-dim">
              FRAMES {settings?.frame_fps ?? "-"} FPS · MAX {settings?.max_pairs ?? "-"} PAIRS / BATCH
            </div>
          </div>

          <div className="control-group">
            <div className="control-label">TARGET CRITERIA (AI) // NEW BATCHES</div>
            <div className="toggle-grid">
              {presets.map((p) => {
                const on = settings?.batch_presets.includes(p.id) ?? false;
                return (
                  <button
                    key={p.id}
                    className={`tactical-toggle preset-toggle ${on ? "active" : ""}`}
                    aria-pressed={on}
                    disabled={!settings}
                    onClick={() => toggleTarget(p.id)}
                  >
                    {p.label.toUpperCase()}
                  </button>
                );
              })}
            </div>
            <input
              type="text"
              className="tactical-input"
              placeholder="custom query, e.g. 'destroyed artillery' [ENTER]"
              value={queryDraft}
              disabled={!settings}
              onChange={(e) => setQueryDraft(e.target.value)}
              onFocus={() => (queryFocused.current = true)}
              onBlur={() => {
                queryFocused.current = false;
                commitQuery();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              }}
            />
            <div className="fs-xs mono text-dim">
              {!settings?.batch_presets.length && !settings?.batch_query
                ? "NONE PICKED: ALL CHANGES (DEFAULT)"
                : `AI LOOKS FOR: ${settings.batch_criteria.toUpperCase()}`}
              {settings && !settings.ai_enabled && " · NO EFFECT WHILE AI IS OFF"}
            </div>
          </div>

          <div className="control-group">
            <div className="control-label">INBOX // {inbox?.watching ? "WATCHING" : "WATCHER OFF"}</div>
            <div className="fs-xs mono text-dim inbox-path">{inbox?.folder}</div>
            {inbox?.waiting.map((n) => (
              <div className="file-status" key={n}>
                <span>{n}</span>
                <span>WAITING FOR PAIR</span>
              </div>
            ))}
            {unbatched.map((g) => (
              <div className="file-status unbatched" key={g.project} title={g.files.join("\n")}>
                <span>{g.site}</span>
                <span>
                  {g.epochs.length} EPOCHS · UNBATCHED
                </span>
              </div>
            ))}
            {inbox?.rejected.map((r) => (
              <div className="file-status rejected" key={r.name} title={r.reason}>
                <span>{r.name}</span>
                <span>BAD NAME</span>
              </div>
            ))}
          </div>

          <div className="control-group">
            <div className="control-label" style={{ display: "flex", justifyContent: "space-between" }}>
              <span>PAIRS</span>
              <span>
                {inbox?.pairs?.filter((p) => p.batched).length ?? 0}/{inbox?.pairs?.length ?? 0} BATCHED
              </span>
            </div>
            {!inbox?.pairs?.length && <div className="fs-xs mono text-dim">NO EPOCH PAIRS IN THE INBOX</div>}
            {inbox?.pairs?.map((p) => {
              const key = pairKey(p);
              const pending = pendingPairs.has(key);
              return (
                <div className={`file-status pair-row ${p.batched ? "batched" : ""}`} key={key} title={`${p.name_a}\n${p.name_b}`}>
                  <span>
                    {p.site} · {p.tag_a} → {p.tag_b}
                  </span>
                  {p.batched ? (
                    <span className="badge batched">BATCHED</span>
                  ) : pending ? (
                    <span className="text-warn">QUEUING...</span>
                  ) : settings?.auto_batch ? (
                    <span className="text-dim">AUTO</span>
                  ) : (
                    <button className="pair-batch" onClick={() => batchOnePair(p)}>
                      BATCH
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          <div className="control-group">
            <div className="control-label" style={{ display: "flex", justifyContent: "space-between" }}>
              <span>BATCH QUEUE [ALT+↑/↓]</span>
              <span>{batches.length}</span>
            </div>
            {batches.map((b) => {
              const s = batchState(b);
              return (
                <button
                  key={b.id}
                  className={`batch-row ${b.id === selectedId ? "active" : ""}`}
                  title={b.ai_enabled ? `TARGETS: ${b.criteria ?? "ALL CHANGES"}` : "CV ONLY: ALL CHANGES"}
                  onClick={() => setSelectedId(b.id)}
                >
                  <div className="batch-row-line">
                    <span>{b.site}</span>
                    <span>
                      {b.tag_a} → {b.tag_b} · {b.legs_count} {b.legs_count === 1 ? "LEG" : "LEGS"}
                    </span>
                  </div>
                  <div className="batch-row-line">
                    <span className={s.cls}>{s.text}</span>
                    <span>
                      {(b.kind_a ?? "?").toUpperCase()}/{(b.kind_b ?? "?").toUpperCase()} · {b.ai_enabled ? "AI" : "CV"} · {b.pairs_count ?? 0} PAIRS ·{" "}
                      {b.pending_count} PEND
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          <div style={{ flexGrow: 1 }} />
          <button className="btn-exec" onClick={requeue} disabled={!selectedId}>
            <span>RE-QUEUE BATCH</span>
            <span className="shortcut-key">[ALT+Q]</span>
          </button>
        </div>
      </aside>

      {/* CENTER PANE: PAIR VIEWER */}
      <main className="pane">
        <div className="pane-header">
          <div className="pane-title">DIFF ENGINE // PAIR REVIEW</div>
          {shown && (
            <div className="fs-xs mono text-warn">
              {shown.name_a} ↔ {shown.name_b}
            </div>
          )}
        </div>
        <div className="pane-content" style={{ padding: 0, position: "relative" }}>
          {center}
          {reportOpen && shown && (
            <ReportViewer batch={shown} onClose={() => setReportOpen(false)} onExport={exportReport} />
          )}
        </div>
      </main>

      {/* RIGHT PANE: FINDINGS & EXPORT */}
      <aside className="pane">
        <div className="pane-header">
          <div className="pane-title">FINDINGS // TRIAGE</div>
          {shown && (
            <div className="fs-xs mono text-dim">
              P {shown.pending_count} · A {shown.accepted_count} · R {shown.rejected_count}
            </div>
          )}
        </div>
        <div className="pane-content">
          {pair && pair.summary && (
            <div className="control-group">
              <div className="control-label">PAIR SUMMARY ({pair.source.toUpperCase()})</div>
              <div className="fs-xs">{pair.summary}</div>
            </div>
          )}

          {pair &&
            CATEGORY_ORDER.map((cat) => {
              const items = order.filter((i) => pair.findings[i].category === cat);
              return (
                <div className="control-group" key={cat}>
                  <div className="finding-group-title">
                    <span>[{CATEGORY_LABELS[cat].toUpperCase()}]</span>
                    <span>{items.length}</span>
                  </div>
                  {items.map((i) => {
                    const f = pair.findings[i];
                    return (
                      <div
                        key={f.id}
                        id={`finding-${i}`}
                        className={`finding-row ${findingIdx === i ? "selected" : ""} review-${f.review_status}`}
                        onClick={() => setFindingIdx(i)}
                      >
                        <div className="finding-head mono">
                          <span>
                            TRGT-{pad2(i + 1)} {f.type.toUpperCase()}
                          </span>
                          <span className={`status-${f.review_status}`}>[{f.review_status.toUpperCase()}]</span>
                        </div>
                        <div className="fs-xs mono text-dim">
                          {f.confidence.toUpperCase()} · {f.sector ?? "-"} · {f.location_text}
                        </div>
                        <div className="fs-xs finding-text">{f.description}</div>
                        <div className="finding-actions">
                          <button
                            className={`tactical-toggle ${f.review_status === "accepted" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setFindingIdx(i);
                              review("accepted", i);
                            }}
                          >
                            [A] ACCEPT
                          </button>
                          <button
                            className={`tactical-toggle ${f.review_status === "rejected" ? "active" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setFindingIdx(i);
                              review("rejected", i);
                            }}
                          >
                            [R] REJECT
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })}

          {!pair && <div className="fs-xs mono text-dim">NO FINDINGS TO REVIEW.</div>}

          <div style={{ flexGrow: 1 }} />

          {shown && shown.warnings.length > 0 && (
            <div className="control-group">
              <div className="control-label">BATCH WARNINGS</div>
              <div className="log-container" style={{ flexGrow: 0, maxHeight: "120px" }}>
                {shown.warnings.map((w, i) => (
                  <div key={i} className="text-warn">
                    {w}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="control-group">
            <div className="control-label">VERIFIED CHANGE REPORT</div>
            <button className="btn-exec" disabled={!shown} onClick={() => setReportOpen((o) => !o)}>
              <span>{reportOpen ? "CLOSE REPORT" : "VIEW REPORT"}</span>
              <span className="shortcut-key">[V]</span>
            </button>
            <button className="tactical-toggle" disabled={!shown} onClick={() => exportReport("html")}>
              [E] EXPORT HTML
            </button>
            <button className="tactical-toggle" disabled={!shown} onClick={() => exportReport("json")}>
              [J] EXPORT JSON
            </button>
            <div className="fs-xs mono text-dim">[←/→] PAIR · [↑/↓] FINDING · [A]/[R]/[U] ACCEPT/REJECT/RESET · [V] REPORT</div>
            <div className={`fs-xs mono ${statusLine.startsWith("[ERR]") ? "text-danger" : "text-dim"}`}>{statusLine}</div>
          </div>
        </div>
      </aside>
    </div>
  );
}
