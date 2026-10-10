import type { AnalyzeResponse } from "../types";

export default function ReportPanel({ data }: { data: AnalyzeResponse }) {
  const r = data.result;
  return (
    <div>
      <h2>Report {r.report_date}</h2>
      <p>{r.summary}</p>
      <ol>
        {r.changes.map((c, i) => (
          <li key={i}>
            <b>{c.type}</b> [{c.sector ?? "?"}] — {c.description} ({c.location_text}) · {c.confidence}
          </li>
        ))}
      </ol>
      <p><b>Recommendation:</b> {r.recommendation}</p>
    </div>
  );
}
