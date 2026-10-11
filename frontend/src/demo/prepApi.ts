// Prep mode client: the demo cache endpoints of the demo prep server (/api/demo, backend/app/demo/routes.py) and
// the sample pairs. The analysis itself goes through the operator terminal's api.ts (analyze, fetchPresets).
import { CACHE_URL, type DemoScene } from "./scene";

const OFFLINE_MSG = "Demo prep server not reachable on http://localhost:8010. Start it with: demo.ps1 prep";

export interface DemoStatus {
  model: string;
  live: boolean; // false: MOCK_LLM=1 or no GEMINI_API_KEY, runs return offline fixtures
  ai_enabled: boolean;
  answer_cache: boolean; // true: an identical re-run returns the stored answer instead of a new model call
  cache_dir: string;
}

export interface Sample {
  id: string;
  name: string;
  description: string;
  criteria: string;
  image_a_url: string;
  image_b_url: string;
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error(OFFLINE_MSG);
  }
  if (res.ok) return res.json();
  // The Vite proxy answers 500/502/504 with an empty body when the backend is down.
  const text = await res.text().catch(() => "");
  if ([500, 502, 504].includes(res.status) && !text.trim()) throw new Error(OFFLINE_MSG);
  let message = text.trim().slice(0, 200) || `HTTP ${res.status}`;
  try {
    const detail = JSON.parse(text)?.detail;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) message = detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ");
  } catch {
    // not JSON
  }
  throw new Error(message);
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const fetchStatus = () => call<DemoStatus>("/api/demo/status");
export const fetchScenes = () => call<{ scenes: DemoScene[] }>("/api/demo/scenes").then((r) => r.scenes);
export const fetchSamples = () => call<Sample[]>("/api/samples");

/** Cache State: freeze a finished job and the exact files it ran on. sceneId replaces that scene in place. */
export function cacheScene(
  jobId: string,
  title: string,
  subtitle: string,
  sources: { a: File; b: File },
  sceneId: string | null
): Promise<DemoScene> {
  const form = new FormData();
  form.append("job_id", jobId);
  form.append("title", title);
  form.append("subtitle", subtitle);
  if (sceneId) form.append("scene_id", sceneId);
  form.append("source_a", sources.a, sources.a.name);
  form.append("source_b", sources.b, sources.b.name);
  return call<DemoScene>("/api/demo/scenes", { method: "POST", body: form });
}

export const renameScene = (id: string, title: string, subtitle: string) =>
  call<DemoScene>(`/api/demo/scenes/${encodeURIComponent(id)}`, json("PATCH", { title, subtitle }));

export const reorderScenes = (ids: string[]) => call<{ scenes: string[] }>("/api/demo/order", json("PUT", { ids }));

export const deleteScene = (id: string) =>
  call<{ deleted: string }>(`/api/demo/scenes/${encodeURIComponent(id)}`, { method: "DELETE" });

/** URL of a cached original upload, or null when the scene was cached without it. */
export const sourceUrl = (scene: DemoScene, key: "source_a" | "source_b") =>
  scene.files[key] ? `${CACHE_URL}/${scene.id}/${scene.files[key]}?v=${encodeURIComponent(scene.cached_at)}` : null;

/** A file served over HTTP (a sample pair, a cached original) as a File the analysis upload accepts. */
export async function fileFromUrl(url: string, name: string): Promise<File> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new Error(`Cannot load ${name}: server not reachable.`);
  }
  if (!res.ok) throw new Error(`Cannot load ${name} (HTTP ${res.status}).`);
  const blob = await res.blob();
  return new File([blob], name, { type: blob.type || "application/octet-stream" });
}
