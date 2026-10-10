import type { AnalyzeResponse } from "./types";

export interface SamplePair {
  id: string;
  name: string;
  description: string;
  criteria: string;
  image_a_url: string;
  image_b_url: string;
}

export async function analyze(
  a: File | Blob,
  b: File | Blob,
  criteria: string,
  lang: string = "en",
  drawGrid: boolean = false
): Promise<AnalyzeResponse> {
  const form = new FormData();
  form.append("image_a", a);
  form.append("image_b", b);
  form.append("criteria", criteria);
  form.append("lang", lang);
  if (drawGrid) {
    form.append("draw_grid", "true");
  }

  const res = await fetch("/api/analyze", { method: "POST", body: form });
  if (!res.ok) {
    let msg = "Analysis failed";
    try {
      const err = await res.json();
      msg = err.detail || msg;
    } catch {
      msg = await res.text();
    }
    throw new Error(msg);
  }
  return res.json();
}

export async function fetchSamples(): Promise<SamplePair[]> {
  const res = await fetch("/api/samples");
  if (!res.ok) {
    throw new Error("Failed to load sample pairs");
  }
  return res.json();
}

export async function fetchImageAsBlob(url: string): Promise<Blob> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch image from ${url}`);
  }
  return res.blob();
}
