import type { AlignMethod, AnalysisResult, AnalyzeResponse } from "./types";

export interface SamplePair {
  id: string;
  name: string;
  description: string;
  criteria: string;
  image_a_url: string;
  image_b_url: string;
}

export interface JobProgress {
  stage: string;
  timings: Record<string, number>;
  status: string;
}

export interface JobHistoryItem {
  job_id: string;
  created_at: string;
  status: string;
  stage: string;
  criteria: string;
  lang: string;
  summary?: string;
  changes_count?: number;
  align_quality?: number;
  align_ok?: boolean;
  align_method?: string;
  timings?: Record<string, number>;
  warnings?: string[];
  images?: Record<string, string>;
  result?: AnalysisResult | null;
  error_message?: string | null;
}

const OFFLINE_MSG = "Backend not reachable on http://localhost:8000. Is uvicorn running?";

// fetch() only rejects on network failure; turn that into a readable message.
async function request(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new Error(OFFLINE_MSG);
  }
}

// Read the body once, then pull FastAPI's `detail` out of it if present.
async function errorMessage(res: Response, fallback: string): Promise<string> {
  // The Vite proxy answers 500/502/504 with an empty body when the backend is down.
  const text = await res.text().catch(() => "");
  if ([500, 502, 504].includes(res.status) && !text.trim()) return OFFLINE_MSG;
  try {
    const detail = JSON.parse(text)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // 422 validation errors: [{loc, msg, type}, ...]
      return detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ");
    }
  } catch {
    // not JSON
  }
  const snippet = text.trim().slice(0, 200);
  return snippet ? `${fallback} (HTTP ${res.status}): ${snippet}` : `${fallback} (HTTP ${res.status})`;
}

export function jobToResponse(job: JobHistoryItem): AnalyzeResponse {
  const method = job.align_method;
  return {
    job_id: job.job_id,
    result: job.result as AnalysisResult,
    align_quality: job.align_quality ?? 0,
    align_ok: Boolean(job.align_ok),
    align_method: method === "sift" || method === "ecc" ? (method as AlignMethod) : "none",
    images: {
      aligned_b_url: job.images?.aligned_b_url || "",
      annotated_url: job.images?.annotated_url || "",
      image_a_url: job.images?.image_a_url,
      heatmap_url: job.images?.heatmap_url,
    },
    timings: job.timings,
    warnings: job.warnings,
    lang: job.lang,
  };
}

export async function submitJob(
  a: File | Blob,
  b: File | Blob,
  criteria: string,
  lang: string = "en",
  drawGrid: boolean = false
): Promise<string> {
  const form = new FormData();
  form.append("image_a", a, a instanceof File ? a.name : "image_a.jpg");
  form.append("image_b", b, b instanceof File ? b.name : "image_b.jpg");
  form.append("criteria", criteria);
  form.append("lang", lang);
  form.append("draw_grid", drawGrid ? "true" : "false");

  const res = await request("/api/analyze", { method: "POST", body: form });
  if (!res.ok) throw new Error(await errorMessage(res, "Analysis failed"));
  const data = await res.json();
  return data.job_id;
}

export async function fetchJob(jobId: string): Promise<JobHistoryItem> {
  const res = await request(`/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(await errorMessage(res, `Failed to load job ${jobId}`));
  return res.json();
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function pollJob(
  jobId: string,
  onProgress?: (progress: JobProgress) => void,
  isCancelled: () => boolean = () => false,
  // Real Gemini with verification + tiling can take several minutes.
  maxWaitMs: number = 10 * 60 * 1000
): Promise<AnalyzeResponse> {
  const start = Date.now();
  let failures = 0;
  while (Date.now() - start < maxWaitMs) {
    if (isCancelled()) throw new CancelledError();

    let job: JobHistoryItem;
    try {
      job = await fetchJob(jobId);
      failures = 0;
    } catch (e) {
      // Tolerate short hiccups (e.g. uvicorn --reload restarting) before giving up.
      if (++failures >= 5) throw e;
      await sleep(1000);
      continue;
    }

    if (isCancelled()) throw new CancelledError();
    onProgress?.({ stage: job.stage, timings: job.timings || {}, status: job.status });

    if (job.status === "done" && job.result) return jobToResponse(job);
    if (job.status === "error") {
      throw new Error(job.error_message || "Reconnaissance processing failed.");
    }
    await sleep(400);
  }
  throw new Error("Analysis job timed out after 10 minutes.");
}

export class CancelledError extends Error {
  constructor() {
    super("cancelled");
    this.name = "CancelledError";
  }
}

export async function analyze(
  a: File | Blob,
  b: File | Blob,
  criteria: string,
  lang: string = "en",
  drawGrid: boolean = false,
  onProgress?: (progress: JobProgress) => void,
  isCancelled?: () => boolean
): Promise<AnalyzeResponse> {
  const jobId = await submitJob(a, b, criteria, lang, drawGrid);
  return pollJob(jobId, onProgress, isCancelled);
}

export async function fetchJobsHistory(limit: number = 30): Promise<JobHistoryItem[]> {
  const res = await request(`/api/jobs?limit=${limit}`);
  if (!res.ok) throw new Error(await errorMessage(res, "Failed to load mission history"));
  return res.json();
}

export async function fetchSamples(): Promise<SamplePair[]> {
  const res = await request("/api/samples");
  if (!res.ok) throw new Error(await errorMessage(res, "Failed to load sample pairs"));
  return res.json();
}

export async function fetchImageAsBlob(url: string): Promise<Blob> {
  const res = await request(url);
  if (!res.ok) throw new Error(await errorMessage(res, `Failed to fetch image ${url}`));
  return res.blob();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch("/api/health");
    return res.ok;
  } catch {
    return false;
  }
}
