import type { AnalyzeResponse } from "./types";

export async function analyze(a: File, b: File, criteria: string): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append("image_a", a);
  form.append("image_b", b);
  form.append("criteria", criteria);
  const res = await fetch("/api/analyze", { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
