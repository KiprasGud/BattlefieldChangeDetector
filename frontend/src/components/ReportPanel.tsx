import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { AnalyzeResponse } from "../types";

interface Props {
  data: AnalyzeResponse;
  selectedIndex: number | null;
  onSelectIndex: (index: number | null) => void;
}

export default function ReportPanel({ data, selectedIndex, onSelectIndex }: Props) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const copyTimer = useRef<number | undefined>(undefined);
  const { result } = data;

  useEffect(() => () => window.clearTimeout(copyTimer.current), []);

  const handleCopyJson = async () => {
    const text = JSON.stringify(result, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("copied");
    } catch {
      // Clipboard API is blocked on non-secure origins (e.g. LAN IP over http).
      setCopyState("failed");
    }
    window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopyState("idle"), 2000);
  };

  const handleDownloadJson = () => {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `zvalgas_report_${data.job_id}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Revoking synchronously can cancel the download in some browsers.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const handlePrintReport = () => window.print();

  const selectCard = (idx: number) => {
    const next = selectedIndex === idx ? null : idx;
    onSelectIndex(next);
    if (next !== null) {
      document.getElementById("result-viewer")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  };

  return (
    <>
      {/* ============================================================
          PRINT-ONLY OPERATOR BRIEFING (hidden on screen).
          Portaled to <body>: print CSS hides .app-container, so it must live outside it.
          ============================================================ */}
      {createPortal(
      <div id="print-report">
        <div style={{ fontFamily: "Arial, sans-serif", color: "#000", padding: "24px" }}>
          {/* Classification banner */}
          <div style={{ background: "#1a1a2e", color: "#00ffee", textAlign: "center", padding: "8px", fontWeight: 700, letterSpacing: "0.2em", fontSize: "14px", marginBottom: "20px" }}>
            ██ ŽVALGAS AI — TACTICAL INTELLIGENCE REPORT ██
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px", fontSize: "12px" }}>
            <div><strong>MISSION ID:</strong> {data.job_id}</div>
            <div><strong>REPORT DATE:</strong> {result.report_date}</div>
            <div><strong>LANG:</strong> {data.lang?.toUpperCase() || "EN"}</div>
          </div>

          {/* Images side by side */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" }}>
            {data.images.image_a_url && (
              <div>
                <div style={{ fontSize: "10px", fontWeight: 700, marginBottom: "4px", textTransform: "uppercase", color: "#555" }}>Baseline (Past)</div>
                <img src={data.images.image_a_url} style={{ width: "100%", border: "1px solid #ccc" }} alt="Baseline" />
              </div>
            )}
            <div>
              <div style={{ fontSize: "10px", fontWeight: 700, marginBottom: "4px", textTransform: "uppercase", color: "#555" }}>Annotated Recon</div>
              <img src={data.images.annotated_url} style={{ width: "100%", border: "1px solid #ccc" }} alt="Annotated" />
            </div>
          </div>

          {/* Situation Assessment */}
          <div style={{ marginBottom: "12px", padding: "10px", border: "1px solid #ccc", borderRadius: "4px" }}>
            <div style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", color: "#555", marginBottom: "4px" }}>Situation Assessment</div>
            <p style={{ fontSize: "12px", margin: 0 }}>{result.summary}</p>
          </div>

          {/* Targets table */}
          <div style={{ marginBottom: "12px" }}>
            <div style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", color: "#555", marginBottom: "6px" }}>Detected Targets</div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px" }}>
              <thead>
                <tr style={{ background: "#1a1a2e", color: "#fff" }}>
                  <th style={{ padding: "5px 8px", textAlign: "left" }}>#</th>
                  <th style={{ padding: "5px 8px", textAlign: "left" }}>Sector</th>
                  <th style={{ padding: "5px 8px", textAlign: "left" }}>Type</th>
                  <th style={{ padding: "5px 8px", textAlign: "left" }}>Confidence</th>
                  <th style={{ padding: "5px 8px", textAlign: "left" }}>Description</th>
                </tr>
              </thead>
              <tbody>
                {result.changes.map((c, idx) => (
                  <tr key={idx} style={{ background: idx % 2 === 0 ? "#f9f9f9" : "#fff" }}>
                    <td style={{ padding: "5px 8px", borderBottom: "1px solid #eee" }}>#{idx + 1}</td>
                    <td style={{ padding: "5px 8px", borderBottom: "1px solid #eee", fontWeight: 600 }}>{c.sector || "—"}</td>
                    <td style={{ padding: "5px 8px", borderBottom: "1px solid #eee", textTransform: "capitalize" }}>{c.type}</td>
                    <td style={{ padding: "5px 8px", borderBottom: "1px solid #eee", color: c.confidence === "high" ? "#166534" : c.confidence === "medium" ? "#92400e" : "#991b1b", fontWeight: 600 }}>
                      {c.confidence.toUpperCase()}
                    </td>
                    <td style={{ padding: "5px 8px", borderBottom: "1px solid #eee" }}>{c.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Recommendation */}
          <div style={{ padding: "10px", border: "1px solid #f59e0b", background: "#fffbeb", borderRadius: "4px", marginBottom: "12px" }}>
            <div style={{ fontSize: "10px", fontWeight: 700, textTransform: "uppercase", color: "#92400e", marginBottom: "4px" }}>Operational Recommendation</div>
            <p style={{ fontSize: "12px", margin: 0 }}>{result.recommendation}</p>
          </div>

          {/* Alignment metadata */}
          <div style={{ fontSize: "10px", color: "#888", borderTop: "1px solid #eee", paddingTop: "8px" }}>
            Alignment: {data.align_ok ? "OK" : "DEGRADED"} ({(data.align_quality * 100).toFixed(0)}% quality, method: {data.align_method || "n/a"})
            {data.timings?.total != null && ` • Total processing: ${data.timings.total}s`}
          </div>

          <div style={{ textAlign: "center", fontSize: "10px", color: "#aaa", marginTop: "16px" }}>
            Generated by Žvalgas AI — Internal Use Only
          </div>
        </div>
      </div>,
      document.body
      )}

      {/* ============================================================
          SCREEN REPORT PANEL
          ============================================================ */}
      <div className="panel">
        {/* Header & Export Actions */}
        <div className="section-head" style={{ borderBottom: "1px solid var(--border-subtle)", paddingBottom: "var(--space-4)" }}>
          <div>
            <h2>Tactical Intelligence Report</h2>
            <div className="mono dim small" style={{ marginTop: "var(--space-1)" }}>
              DATE: {result.report_date} • TARGETS DETECTED: {result.changes.length}
            </div>
          </div>

          <div className="chip-row">
            <button
              type="button"
              id="copy-report-json-btn"
              onClick={handleCopyJson}
              className="btn-secondary"
            >
              {copyState === "copied" ? "✓ Copied" : copyState === "failed" ? "✕ Clipboard blocked" : "📋 Copy JSON"}
            </button>
            <button
              type="button"
              id="download-report-json-btn"
              onClick={handleDownloadJson}
              className="btn-secondary"
            >
              💾 Download JSON
            </button>
            <a
              id="download-annotated-img-btn"
              href={data.images.annotated_url}
              download={`annotated_${data.job_id}.jpg`}
              className="btn-secondary"
              style={{ textDecoration: "none" }}
            >
              🖼️ Download Image
            </a>
            <button
              type="button"
              id="print-report-btn"
              onClick={handlePrintReport}
              className="btn-secondary"
            >
              🖨️ Print Briefing
            </button>
          </div>
        </div>

        {/* Situation & Recommendation cards */}
        <div className="upload-grid">
          <div style={{ background: "var(--bg-app)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: "var(--space-4)" }}>
            <div className="mono upper small" style={{ color: "var(--brand-base)", letterSpacing: "0.08em", marginBottom: "var(--space-2)", fontWeight: 600 }}>
              Situation Assessment
            </div>
            <p className="dim">
              {result.summary}
            </p>
          </div>

          <div style={{ background: "var(--bg-app)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", padding: "var(--space-4)" }}>
            <div className="mono upper small" style={{ color: "var(--accent-warning)", letterSpacing: "0.08em", marginBottom: "var(--space-2)", fontWeight: 600 }}>
              Operational Recommendation
            </div>
            <p className="dim">
              {result.recommendation}
            </p>
          </div>
        </div>

        {/* Target Changes List */}
        <div>
          <div className="section-head">
            <h3>
              Detected Targets ({result.changes.length})
            </h3>
            <span className="xsmall dim">
              Click to highlight target on imagery
            </span>
          </div>

          {result.changes.length === 0 ? (
            <div className="empty-state">
              No changes detected matching specified criteria.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
              {result.changes.map((c, idx) => {
                const isSelected = selectedIndex === idx;
                const confClass =
                  c.confidence === "high"
                    ? "badge-high"
                    : c.confidence === "medium"
                    ? "badge-medium"
                    : "badge-low";

                return (
                  <div
                    key={idx}
                    id={`change-card-${idx}`}
                    className="change-card"
                    role="button"
                    tabIndex={0}
                    aria-pressed={isSelected}
                    onClick={() => selectCard(idx)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        selectCard(idx);
                      }
                    }}
                    style={{
                      background: isSelected ? "rgba(37, 99, 235, 0.05)" : "var(--bg-app)",
                      borderColor: isSelected ? "var(--brand-base)" : "var(--border-subtle)",
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                      boxShadow: isSelected ? "0 0 0 1px var(--brand-base)" : "none",
                    }}
                  >
                    <div style={{ 
                        background: isSelected ? "var(--brand-base)" : "var(--bg-app)",
                        border: "1px solid",
                        borderColor: isSelected ? "var(--brand-base)" : "var(--border-subtle)",
                        width: "32px", height: "32px", borderRadius: "var(--radius-md)", 
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontFamily: "var(--font-mono)", fontWeight: 600, color: isSelected ? "#fff" : "var(--text-main)",
                        fontSize: "14px"
                    }}>
                      #{idx + 1}
                    </div>

                    <div>
                      <div className="chip-row" style={{ marginBottom: "var(--space-1)" }}>
                        <span style={{ fontWeight: 600, textTransform: "capitalize" }}>
                          {c.type}
                        </span>
                        {c.sector && (
                          <span className="badge badge-sector">Sector {c.sector}</span>
                        )}
                        <span className={`badge ${confClass}`}>
                          {c.confidence} confidence
                        </span>
                      </div>
                      <p className="dim small" style={{ marginBottom: "var(--space-1)" }}>
                        {c.description}
                      </p>
                      <div className="xsmall mono dim">
                        Location: {c.location_text} • Box: [{c.box.join(", ")}]
                      </div>
                    </div>

                    <div className="history-open" style={{ color: isSelected ? "var(--brand-base)" : "var(--text-muted)" }}>
                      {isSelected ? "● Viewing" : "○ Inspect"}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
