import type { AnalyzeResponse } from "../types";

export default function ResultViewer({ data }: { data: AnalyzeResponse }) {
  return (
    <div>
      {!data.align_ok && <p style={{ color: "orange" }}>Warning: poor image alignment ({data.align_quality.toFixed(2)})</p>}
      <img src={data.images.annotated_url} style={{ maxWidth: "100%" }} alt="Annotated changes" />
    </div>
  );
}
