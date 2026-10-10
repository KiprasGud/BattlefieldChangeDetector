import type { BatchDetail, Finding, FramePair } from "../api";
import { CATEGORY_LABELS, CATEGORY_ORDER } from "../types";

// The verified change report, read in place: same rule as the exported one (backend render/report.py) - accepted
// findings only, pairs without one left out - grouped by leg (Day1 -> Day2) with the boxes drawn over both frames.

const pad2 = (n: number) => String(n).padStart(2, "0");
const clock = (t: number) => `${pad2(Math.floor(t / 60))}:${pad2(Math.floor(t % 60))}`;
const pct = (v: number) => `${Math.round(v * 100)}%`;

interface Props {
  batch: BatchDetail;
  onClose: () => void;
  onExport: (format: "html" | "json") => void;
}

function Frame({ src, label, findings }: { src: string; label: string; findings: Finding[] }) {
  return (
    <figure className="report-frame">
      <div className="report-frame-img">
        <img src={src} alt={label} />
        {findings.map((f, i) => {
          const [ymin, xmin, ymax, xmax] = f.box;
          return (
            <div
              key={f.id}
              className="report-box"
              style={{
                top: `${ymin / 10}%`,
                left: `${xmin / 10}%`,
                height: `${(ymax - ymin) / 10}%`,
                width: `${(xmax - xmin) / 10}%`,
              }}
            >
              <span className="mono">#{i + 1}</span>
            </div>
          );
        })}
      </div>
      <figcaption className="fs-xs mono text-dim">{label}</figcaption>
    </figure>
  );
}

export default function ReportViewer({ batch, onClose, onExport }: Props) {
  const verified: FramePair[] = batch.pairs
    .map((p) => ({ ...p, findings: p.findings.filter((f) => f.review_status === "accepted") }))
    .filter((p) => p.findings.length > 0);

  const totals = CATEGORY_ORDER.map((cat) => ({
    cat,
    n: verified.reduce((sum, p) => sum + p.findings.filter((f) => (f.category ?? "unknown_anomaly") === cat).length, 0),
  }));
  const total = totals.reduce((sum, t) => sum + t.n, 0);
  const legs = batch.legs.filter((leg) => verified.some((p) => p.leg_idx === leg.idx));
  const time = (kind: string | null, t: number) => (kind === "image" ? "STILL" : clock(t));

  return (
    <div className="report-viewer">
      <div className="report-head">
        <div className="pane-title">VERIFIED CHANGE REPORT // {batch.site}</div>
        <div className="report-actions">
          <button className="tactical-toggle" onClick={() => onExport("html")}>[E] EXPORT HTML</button>
          <button className="tactical-toggle" onClick={() => onExport("json")}>[J] EXPORT JSON</button>
          <button className="tactical-toggle" onClick={onClose}>[ESC] CLOSE</button>
        </div>
      </div>

      <div className="report-body">
        <div className="report-meta fs-xs mono">
          <span>SITE: {batch.site}</span>
          <span>LEGS: {batch.legs.map((l) => `${l.tag_a}→${l.tag_b}`).join(", ") || "-"}</span>
          <span>AI: {batch.ai_enabled ? "ON" : "OFF"}</span>
          <span>STATUS: {batch.status.toUpperCase()}</span>
          <span>BATCH: {batch.id}</span>
        </div>

        <table className="report-table report-totals">
          <thead>
            <tr>
              <th>Category</th>
              <th>Verified</th>
            </tr>
          </thead>
          <tbody>
            {totals.map(({ cat, n }) => (
              <tr key={cat}>
                <td>{CATEGORY_LABELS[cat]}</td>
                <td className="mono">{n}</td>
              </tr>
            ))}
            <tr>
              <td className="mono">TOTAL</td>
              <td className="mono">{total}</td>
            </tr>
          </tbody>
        </table>

        {!verified.length && (
          <div className="wireframe-placeholder report-empty">
            <div>NO VERIFIED CHANGES</div>
            <div className="fs-xs mono">ACCEPT FINDINGS [A] IN THE TRIAGE PANE FIRST.</div>
          </div>
        )}

        {legs.map((leg) => (
          <section key={leg.id} className="report-leg">
            <div className="report-leg-title mono">
              <span>
                LEG {pad2(leg.idx)} · {leg.tag_a.toUpperCase()} → {leg.tag_b.toUpperCase()}
              </span>
              <span className="text-dim">
                {leg.name_a} ↔ {leg.name_b}
              </span>
            </div>

            {verified
              .filter((p) => p.leg_idx === leg.idx)
              .map((p) => (
                <div key={p.id} className="report-pair">
                  <div className="fs-xs mono">
                    <span className="text-warn">PAIR {pad2(p.idx)}</span> · A@{time(p.kind_a, p.time_a)} ↔ B@
                    {time(p.kind_b, p.time_b)}
                    <span className="text-dim">
                      {" "}
                      · INL {p.inliers} · OVL {pct(p.overlap)} · SSIM {p.ssim.toFixed(2)} · SRC {p.source.toUpperCase()}
                    </span>
                  </div>
                  <div className="report-frames">
                    <Frame src={p.images.image_a_url} label={`BEFORE · ${p.tag_a}`} findings={p.findings} />
                    <Frame src={p.images.aligned_b_url} label={`AFTER · ${p.tag_b} (ALIGNED)`} findings={p.findings} />
                  </div>
                  {p.summary && <div className="fs-xs">{p.summary}</div>}
                  <table className="report-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Category</th>
                        <th>Type</th>
                        <th>Conf.</th>
                        <th>Sector</th>
                        <th>Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.findings.map((f, i) => (
                        <tr key={f.id}>
                          <td className="mono">#{i + 1}</td>
                          <td>{CATEGORY_LABELS[f.category] ?? f.category}</td>
                          <td>{f.type}</td>
                          <td className="mono">{f.confidence.toUpperCase()}</td>
                          <td className="mono">{f.sector ?? "-"}</td>
                          <td>
                            {f.description}
                            {f.location_text && <div className="text-dim">{f.location_text}</div>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
          </section>
        ))}
      </div>
    </div>
  );
}
