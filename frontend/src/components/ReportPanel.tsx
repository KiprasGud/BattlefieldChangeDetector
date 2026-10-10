import React, { useState } from "react";
import type { AnalyzeResponse } from "../types";

interface Props {
  data: AnalyzeResponse;
  selectedIndex: number | null;
  onSelectIndex: (index: number | null) => void;
}

export default function ReportPanel({ data, selectedIndex, onSelectIndex }: Props) {
  const [copied, setCopied] = useState(false);
  const { result } = data;

  const handleCopyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(result, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadJson = () => {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `zvalgas_report_${data.job_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="glass-panel" style={{ padding: "24px" }}>
      {/* Header & Export Actions */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", marginBottom: "20px", paddingBottom: "16px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div>
          <h2 style={{ fontSize: "1.15rem", fontWeight: 700, letterSpacing: "0.02em" }}>
            Tactical Intelligence Report
          </h2>
          <div style={{ fontSize: "0.78rem", fontFamily: "var(--font-mono)", color: "var(--text-dim)", marginTop: "3px" }}>
            DATE: {result.report_date} • TARGETS DETECTED: {result.changes.length}
          </div>
        </div>

        <div style={{ display: "flex", gap: "10px" }}>
          <button
            type="button"
            id="copy-report-json-btn"
            onClick={handleCopyJson}
            className="btn-secondary"
            style={{ fontSize: "0.8rem" }}
          >
            {copied ? "✓ Copied to Clipboard" : "📋 Copy Report JSON"}
          </button>
          <button
            type="button"
            id="download-report-json-btn"
            onClick={handleDownloadJson}
            className="btn-secondary"
            style={{ fontSize: "0.8rem" }}
          >
            💾 Download JSON
          </button>
          <a
            id="download-annotated-img-btn"
            href={data.images.annotated_url}
            download={`annotated_${data.job_id}.jpg`}
            className="btn-secondary"
            style={{ fontSize: "0.8rem", textDecoration: "none" }}
          >
            🖼️ Download Image
          </a>
        </div>
      </div>

      {/* Situation Summary & Tactical Recommendations */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "16px", marginBottom: "24px" }}>
        {/* Situation Assessment */}
        <div style={{ background: "rgba(15, 23, 42, 0.6)", border: "1px solid var(--border-subtle)", borderRadius: "8px", padding: "16px" }}>
          <div style={{ fontSize: "0.76rem", fontFamily: "var(--font-mono)", color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "6px" }}>
            Situation Assessment
          </div>
          <p style={{ fontSize: "0.92rem", color: "var(--text-main)", lineHeight: 1.55 }}>
            {result.summary}
          </p>
        </div>

        {/* Operational Recommendation */}
        <div style={{ background: "rgba(15, 23, 42, 0.6)", border: "1px solid var(--border-subtle)", borderRadius: "8px", padding: "16px" }}>
          <div style={{ fontSize: "0.76rem", fontFamily: "var(--font-mono)", color: "var(--accent-amber)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "6px" }}>
            Operational Recommendation
          </div>
          <p style={{ fontSize: "0.92rem", color: "var(--text-main)", lineHeight: 1.55 }}>
            {result.recommendation}
          </p>
        </div>
      </div>

      {/* Target Changes List */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
          <h3 style={{ fontSize: "0.95rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--text-muted)" }}>
            Detected Targets & Modifications ({result.changes.length})
          </h3>
          <span style={{ fontSize: "0.74rem", color: "var(--text-dim)" }}>
            Click an item to highlight its location in the imagery viewer
          </span>
        </div>

        {result.changes.length === 0 ? (
          <div style={{ padding: "30px", textAlign: "center", color: "var(--text-dim)", background: "rgba(15, 23, 42, 0.4)", borderRadius: "8px" }}>
            No changes detected matching specified criteria.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
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
                  onClick={() => onSelectIndex(isSelected ? null : idx)}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr auto",
                    alignItems: "start",
                    gap: "16px",
                    padding: "14px 18px",
                    borderRadius: "8px",
                    background: isSelected ? "rgba(6, 182, 212, 0.12)" : "rgba(15, 23, 42, 0.5)",
                    border: `1px solid ${isSelected ? "var(--accent-cyan)" : "var(--border-subtle)"}`,
                    boxShadow: isSelected ? "0 0 16px rgba(6, 182, 212, 0.2)" : "none",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {/* Target Index Badge */}
                  <div
                    style={{
                      width: "32px",
                      height: "32px",
                      borderRadius: "6px",
                      background: isSelected ? "var(--accent-cyan)" : "#1e293b",
                      color: isSelected ? "#000" : "var(--text-main)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontFamily: "var(--font-mono)",
                      fontWeight: 700,
                      fontSize: "0.85rem",
                    }}
                  >
                    #{idx + 1}
                  </div>

                  {/* Details */}
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                      <span style={{ fontWeight: 600, fontSize: "0.92rem", color: "var(--text-main)", textTransform: "capitalize" }}>
                        {c.type}
                      </span>
                      {c.sector && (
                        <span className="badge badge-sector">
                          Sector {c.sector}
                        </span>
                      )}
                      <span className={`badge ${confClass}`}>
                        {c.confidence} confidence
                      </span>
                    </div>

                    <p style={{ fontSize: "0.84rem", color: "var(--text-muted)", marginBottom: "4px" }}>
                      {c.description}
                    </p>

                    <div style={{ fontSize: "0.75rem", fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
                      Location: {c.location_text} • Box: [{c.box.join(", ")}]
                    </div>
                  </div>

                  {/* Indicator Arrow */}
                  <div style={{ fontSize: "0.9rem", color: isSelected ? "var(--accent-cyan)" : "var(--text-dim)" }}>
                    {isSelected ? "● Viewing" : "○ Inspect"}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
