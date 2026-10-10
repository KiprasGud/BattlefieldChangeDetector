import { useState } from "react";

const PRESETS = ["New vehicle tracks", "Craters / digging", "Felled trees", "New cables / lines"];

interface Props {
  onSubmit: (a: File, b: File, criteria: string) => void;
  loading: boolean;
}

export default function UploadPanel({ onSubmit, loading }: Props) {
  const [a, setA] = useState<File | null>(null);
  const [b, setB] = useState<File | null>(null);
  const [criteria, setCriteria] = useState(PRESETS[0]);

  return (
    <div>
      <label>Before (A): <input type="file" accept="image/*" onChange={(e) => setA(e.target.files?.[0] ?? null)} /></label>
      <br />
      <label>After (B): <input type="file" accept="image/*" onChange={(e) => setB(e.target.files?.[0] ?? null)} /></label>
      <div style={{ margin: "8px 0" }}>
        {PRESETS.map((p) => (
          <button key={p} onClick={() => setCriteria(p)} style={{ marginRight: 6 }}>{p}</button>
        ))}
      </div>
      <textarea rows={2} style={{ width: "100%" }} value={criteria} onChange={(e) => setCriteria(e.target.value)} />
      <button disabled={!a || !b || loading} onClick={() => a && b && onSubmit(a, b, criteria)}>
        {loading ? "Analyzing..." : "Analyze"}
      </button>
    </div>
  );
}
