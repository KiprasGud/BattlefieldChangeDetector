// Cached demo scenes (docs/demo.md), read as static files from /demo_cache: never through the API.
import type { AnalysisResult } from "../types";

export const CACHE_URL = "/demo_cache";

/** Mirrors scene.json written by backend/app/demo/store.py. */
export interface DemoScene {
  id: string;
  title: string;
  subtitle: string;
  cached_at: string;
  source_job: string;
  criteria: string; // the text the AI was given: target class labels + the custom query
  presets: string[];
  query: string;
  lang: string;
  source: "gemini" | "fixtures" | "ai_off"; // where the detections came from
  model: string | null; // set when source is "gemini"
  prompt_version: number;
  size: { w: number; h: number }; // image A's frame, which every scene image shares
  align: { ok: boolean; quality: number; method: string };
  warnings: string[];
  timings: Record<string, number>;
  result: AnalysisResult; // the AI output, as returned
  files: { image_a: string; aligned_b: string; annotated: string; source_a?: string; source_b?: string };
}

export type SceneImage = "image_a" | "aligned_b" | "annotated";

/** URL of a scene image. The cache time changes when a scene is re-cached in place, so the browser may keep it. */
export const sceneFile = (scene: DemoScene, file: SceneImage) =>
  `${CACHE_URL}/${scene.id}/${scene.files[file]}?v=${encodeURIComponent(scene.cached_at)}`;

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

/** Every cached scene in presentation order; a missing or broken scene is left out. */
export async function loadScenes(): Promise<DemoScene[]> {
  const manifest = await getJson<{ scenes?: string[] }>(`${CACHE_URL}/manifest.json`);
  const scenes = await Promise.all(
    (manifest?.scenes ?? []).map((id) => getJson<DemoScene>(`${CACHE_URL}/${encodeURIComponent(id)}/scene.json`))
  );
  return scenes.filter((s): s is DemoScene => !!s?.result && !!s.files);
}

const preloaded: HTMLImageElement[] = []; // held so the browser keeps them decoded

/** Fetch and decode images ahead of time, so switching scenes never waits for the disk or the decoder. */
export function preloadImages(urls: string[]): Promise<void> {
  return Promise.all(
    urls.map((url) => {
      const img = new Image();
      img.src = url;
      preloaded.push(img);
      return img.decode().catch(() => undefined);
    })
  ).then(() => undefined);
}
