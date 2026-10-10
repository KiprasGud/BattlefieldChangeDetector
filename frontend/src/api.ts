import type { AlignMethod, AnalysisResult, AnalyzeResponse, Category, Confidence } from "./types";

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

/** What to detect: pre-made target class ids (GET /api/presets) and/or a free-text query. The backend turns
 *  both into one written instruction for the AI model. */
export interface Criteria {
  presets: string[];
  query: string;
}

export interface Preset {
  id: string;
  label: string;
  shortcut: string;
}

export async function fetchPresets(): Promise<Preset[]> {
  const res = await request("/api/presets");
  if (!res.ok) throw new Error(await errorMessage(res, "Failed to load target classes"));
  return res.json();
}

export async function submitJob(
  a: File | Blob,
  b: File | Blob,
  criteria: Criteria,
  lang: string = "en",
  drawGrid: boolean = false
): Promise<string> {
  const form = new FormData();
  form.append("image_a", a, a instanceof File ? a.name : "image_a.jpg");
  form.append("image_b", b, b instanceof File ? b.name : "image_b.jpg");
  form.append("presets", criteria.presets.join(","));
  form.append("criteria", criteria.query);
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
  criteria: Criteria,
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

// --- watch-folder batches and review (GET/POST /api/batches, /api/findings, /api/settings, /api/inbox) ---

export type ReviewStatus = "pending" | "accepted" | "rejected";

export interface Finding {
  id: string;
  batch_id: string;
  pair_id: string;
  idx: number;
  category: Category;
  type: string;
  description: string;
  location_text: string;
  confidence: Confidence;
  box: [number, number, number, number];
  sector: string | null;
  review_status: ReviewStatus;
  reviewed_at: string | null;
}

export interface FramePair {
  id: string;
  batch_id: string;
  idx: number;
  frame_a: number;
  frame_b: number;
  time_a: number; // seconds into source A (display only)
  time_b: number;
  inliers: number;
  overlap: number; // shared ground, 0-1
  ssim: number; // structural similarity after alignment, 0-1
  align_quality: number;
  align_method: string;
  change_ratio: number;
  source: "ai" | "cv";
  summary: string;
  recommendation: string;
  images: { image_a_url: string; aligned_b_url: string; heatmap_url: string; annotated_url: string };
  findings: Finding[];
}

export interface Batch {
  id: string;
  created_at: string;
  updated_at: string;
  site: string;
  name_a: string;
  name_b: string;
  tag_a: string;
  tag_b: string;
  kind_a: "image" | "video" | null;
  kind_b: "image" | "video" | null;
  ai_enabled: boolean;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  progress: string;
  frames_a: number | null;
  frames_b: number | null;
  matched_pairs: number | null;
  pairs_count: number | null;
  timings: Record<string, number>;
  warnings: string[];
  error_message: string | null;
  findings_count: number;
  pending_count: number;
  accepted_count: number;
  rejected_count: number;
}

export interface BatchDetail extends Batch {
  pairs: FramePair[];
}

export interface PipelineSettings {
  ai_enabled: boolean;
  ai_available: boolean;
  watch_enabled: boolean;
  watch_dir: string;
  frame_fps: number;
  max_pairs: number;
}

export interface InboxState {
  watching: boolean;
  folder: string;
  scheme: string;
  waiting: string[];
  paired: string[];
  rejected: { name: string; reason: string }[];
}

async function getJson<T>(url: string, what: string): Promise<T> {
  const res = await request(url);
  if (!res.ok) throw new Error(await errorMessage(res, `Failed to load ${what}`));
  return res.json();
}

async function sendJson<T>(url: string, method: string, body: unknown, what: string): Promise<T> {
  const res = await request(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res, what));
  return res.json();
}

export const fetchSettings = () => getJson<PipelineSettings>("/api/settings", "settings");
export const fetchInbox = () => getJson<InboxState>("/api/inbox", "inbox");
export const fetchBatches = (limit: number = 50) => getJson<Batch[]>(`/api/batches?limit=${limit}`, "batches");
export const fetchBatch = (id: string) => getJson<BatchDetail>(`/api/batches/${id}`, `batch ${id}`);

export const updateSettings = (aiEnabled: boolean) =>
  sendJson<PipelineSettings>("/api/settings", "PUT", { ai_enabled: aiEnabled }, "Settings update failed");

export const reviewFinding = (id: string, status: ReviewStatus) =>
  sendJson<Finding>(`/api/findings/${id}/review`, "POST", { status }, "Review failed");

export async function rerunBatch(id: string): Promise<string> {
  const data = await sendJson<{ batch_id: string }>(`/api/batches/${id}/rerun`, "POST", undefined, "Re-queue failed");
  return data.batch_id;
}

export const reportUrl = (id: string, format: "html" | "json") => `/api/batches/${id}/report?format=${format}`;
