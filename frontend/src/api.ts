import type { AlignMethod, AnalysisResult, AnalyzeResponse, Category, Confidence } from "./types";

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

/** A stored align method as the AlignMethod union; anything else is "none". */
export const toAlignMethod = (method?: string | null): AlignMethod =>
  method === "sift" || method === "ecc" ? method : "none";

export function jobToResponse(job: JobHistoryItem): AnalyzeResponse {
  return {
    job_id: job.job_id,
    result: job.result as AnalysisResult,
    align_quality: job.align_quality ?? 0,
    align_ok: Boolean(job.align_ok),
    align_method: toAlignMethod(job.align_method),
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

export const fetchPresets = () => getJson<Preset[]>("/api/presets", "target classes");

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

export const fetchJob = (jobId: string) => getJson<JobHistoryItem>(`/api/jobs/${jobId}`, `job ${jobId}`);

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
  leg_idx: number;
  tag_a: string; // epochs of the pair's leg, e.g. Day1 -> Day2
  tag_b: string;
  kind_a: "image" | "video" | null;
  kind_b: "image" | "video" | null;
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

/** One consecutive epoch comparison of a project batch (Day1 -> Day2). */
export interface Leg {
  id: string;
  batch_id: string;
  idx: number;
  tag_a: string;
  tag_b: string;
  name_a: string;
  name_b: string;
  kind_a: "image" | "video" | null;
  kind_b: "image" | "video" | null;
  status: "pending" | "running" | "done" | "error";
  frames_a: number | null;
  frames_b: number | null;
  matched_pairs: number | null;
  timings: Record<string, number>;
  warnings: string[];
  error_message: string | null;
}

/** One project: all of its epochs, as legs. *_a is the first epoch, *_b the latest. */
export interface Batch {
  id: string;
  created_at: string;
  updated_at: string;
  site: string;
  project: string;
  legs_count: number;
  name_a: string;
  name_b: string;
  tag_a: string;
  tag_b: string;
  kind_a: "image" | "video" | null;
  kind_b: "image" | "video" | null;
  ai_enabled: boolean;
  criteria: string | null; // what the AI was asked to find, fixed when queued (null: older batch)
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
  legs: Leg[];
  pairs: FramePair[];
}

export interface PipelineSettings {
  ai_enabled: boolean;
  ai_available: boolean;
  auto_batch: boolean; // false: new files stay in the inbox unbatched, the worker is paused
  batch_presets: string[]; // target class ids for batches queued from now on
  batch_query: string; // free-text query for batches queued from now on
  batch_criteria: string; // the text the AI gets: presets + query, or the "any real change" default
  queued_count: number;
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
  groups: InboxGroup[];
  pairs: InboxPair[];
}

/** One consecutive epoch pair (Day1 -> Day2) in the inbox; listed whether batched or not. */
export interface InboxPair {
  project: string;
  site: string;
  name_a: string;
  name_b: string;
  tag_a: string;
  tag_b: string;
  batched: boolean;
}

/** A project in the inbox with at least two epochs; batched when all of its legs are in a batch. */
export interface InboxGroup {
  project: string;
  site: string;
  files: string[];
  epochs: string[];
  batched: boolean;
}

export const fetchSettings = () => getJson<PipelineSettings>("/api/settings", "settings");
export const fetchInbox = () => getJson<InboxState>("/api/inbox", "inbox");
export const fetchBatches = (limit: number = 50) => getJson<Batch[]>(`/api/batches?limit=${limit}`, "batches");
export const fetchBatch = (id: string) => getJson<BatchDetail>(`/api/batches/${id}`, `batch ${id}`);

export const updateSettings = (
  patch: Partial<Pick<PipelineSettings, "ai_enabled" | "auto_batch" | "batch_presets" | "batch_query">>
) =>
  sendJson<PipelineSettings>("/api/settings", "PUT", patch, "Settings update failed");

/** Flush the batch queue (only while automatic batching is stopped); its files go back to the inbox, unbatched. */
export const clearQueue = () =>
  sendJson<{ deleted: string[]; files: string[] }>("/api/queue/clear", "POST", undefined, "Clear queue failed");

/** Batch one inbox pair by hand and run it now, also while automatic batching is stopped. */
export const batchPair = (name_a: string, name_b: string) =>
  sendJson<{ batch_id: string | null; started: boolean }>("/api/inbox/batch", "POST", { name_a, name_b }, "Batch failed");

export const reviewFinding = (id: string, status: ReviewStatus) =>
  sendJson<Finding>(`/api/findings/${id}/review`, "POST", { status }, "Review failed");

export async function rerunBatch(id: string): Promise<string> {
  const data = await sendJson<{ batch_id: string }>(`/api/batches/${id}/rerun`, "POST", undefined, "Re-queue failed");
  return data.batch_id;
}

export type ReportFormat = "html" | "json" | "pdf";
export const reportUrl = (id: string, format: ReportFormat) => `/api/batches/${id}/report?format=${format}`;
