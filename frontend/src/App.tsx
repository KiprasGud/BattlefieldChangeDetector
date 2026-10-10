import { useState } from "react";
import { analyze } from "./api";
import type { AnalyzeResponse } from "./types";
import UploadPanel from "./components/UploadPanel";
import ResultViewer from "./components/ResultViewer";
import ReportPanel from "./components/ReportPanel";

export default function App() {
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(a: File, b: File, criteria: string) {
    setLoading(true);
    setError(null);
    try {
      setData(await analyze(a, b, criteria));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ fontFamily: "sans-serif", maxWidth: 1100, margin: "0 auto", padding: 16 }}>
      <h1>Žvalgas AI</h1>
      <UploadPanel onSubmit={run} loading={loading} />
      {error && <p style={{ color: "red" }}>{error}</p>}
      {data && (
        <>
          <ResultViewer data={data} />
          <ReportPanel data={data} />
        </>
      )}
    </div>
  );
}
