import type { AnalyzeResponse } from "./types";

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
  result?: any;
}

export async function submitJob(
  a: File | Blob,
  b: File | Blob,
  criteria: string,
  lang: string = "en",
  drawGrid: boolean = false
): Promise<string> {
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
  const data = await res.json();
  return data.job_id;
}

export async function fetchJob(jobId: string): Promise<JobHistoryItem> {
  const res = await fetch(`/api/jobs/${jobId}`);
  if (!res.ok) {
    throw new Error(`Failed to load job ${jobId}`);
  }
  return res.json();
}

export async function pollJob(
  jobId: string,
  onProgress?: (progress: JobProgress) => void,
  maxWaitMs: number = 180000
): Promise<AnalyzeResponse> {
  const start = Date.now();
  while (Date.now() - start < maxWaitMs) {
    const job = await fetchJob(jobId);
    if (onProgress) {
      onProgress({
        stage: job.stage,
        timings: job.timings || {},
        status: job.status,
      });
    }

    if (job.status === "done" && job.result) {
      return {
        job_id: job.job_id,
        result: job.result,
        align_quality: job.align_quality ?? 0,
        align_ok: Boolean(job.align_ok),
        align_method: (job.align_method as any) || "none",
        images: {
          aligned_b_url: job.images?.aligned_b_url || "",
          annotated_url: job.images?.annotated_url || "",
          image_a_url: job.images?.image_a_url,
          heatmap_url: job.images?.heatmap_url,
        },
        timings: job.timings,
        warnings: job.warnings,
      };
    }

    if (job.status === "error") {
      throw new Error((job as any).error_message || "Reconnaissance processing failed.");
    }

    // Wait 250ms before next poll
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Analysis job timed out.");
}

export async function analyze(
  a: File | Blob,
  b: File | Blob,
  criteria: string,
  lang: string = "en",
  drawGrid: boolean = false,
  onProgress?: (progress: JobProgress) => void
): Promise<AnalyzeResponse> {
  const jobId = await submitJob(a, b, criteria, lang, drawGrid);
  return pollJob(jobId, onProgress);
}

export async function fetchJobsHistory(limit: number = 30): Promise<JobHistoryItem[]> {
  const res = await fetch(`/api/jobs?limit=${limit}`);
  if (!res.ok) {
    throw new Error("Failed to load mission history");
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
