// Demo presentation layer (docs/demo.md). Its own config: the operator terminal keeps vite.config.ts as it is.
//   dev      :5174  prep.html + demo.html, /api -> demo prep server on :8010         (demo.ps1 prep)
//   build    dist-demo/ with demo.html only: the audience server cannot serve the prep page
//   preview  :5175  the built presentation, no API proxy                             (demo.ps1, present.cmd)
// Both serve the cached scenes from <repo>/demo_cache (DEMO_CACHE_DIR, absolute) at /demo_cache, read from disk
// on every request, so caching a scene never needs a rebuild.
import { readFile } from "node:fs/promises";
import type { ServerResponse } from "node:http";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Connect, type Plugin } from "vite";

const root = fileURLToPath(new URL(".", import.meta.url));
const CACHE_DIR = resolve(root, process.env.DEMO_CACHE_DIR || "../demo_cache");

const TYPES: Record<string, string> = {
  ".json": "application/json; charset=utf-8",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".bmp": "image/bmp",
  ".tif": "image/tiff",
  ".tiff": "image/tiff",
};

function notFound(res: ServerResponse) {
  res.statusCode = 404;
  res.end("Not found");
}

// GET /demo_cache/<path>: a file inside the cache folder, never anything outside it. Versioned image URLs
// (?v=<cached_at>) change whenever a scene is re-cached, so they may be cached for good; the JSON may not.
const serveCache: Connect.NextHandleFunction = async (req, res) => {
  const [path, query = ""] = (req.url ?? "/").split("?");
  let file: string;
  try {
    file = resolve(CACHE_DIR, "." + decodeURIComponent(path));
  } catch {
    return notFound(res); // malformed %-escape
  }
  if (!file.startsWith(CACHE_DIR + sep)) return notFound(res);
  let data: Buffer;
  try {
    // Read whole, never stream: no handle stays open after an aborted request, and on Windows an open handle
    // stops prep mode from replacing manifest.json or a re-cached scene.
    data = await readFile(file);
  } catch {
    return notFound(res); // missing, or a folder
  }
  res.writeHead(200, {
    "Content-Type": TYPES[extname(file).toLowerCase()] ?? "application/octet-stream",
    "Content-Length": data.length,
    "Cache-Control": /(^|&)v=/.test(query) ? "public, max-age=31536000, immutable" : "no-cache",
  });
  res.end(data);
};

const demoCache = (): Plugin => ({
  name: "demo-cache",
  configureServer(server) {
    server.middlewares.use("/demo_cache", serveCache);
  },
  configurePreviewServer(server) {
    server.middlewares.use("/demo_cache", serveCache);
    // The built presentation is demo.html: send the bare address there.
    server.middlewares.use((req, res, next) => {
      if (req.url !== "/") return next();
      res.writeHead(302, { Location: "/demo.html" });
      res.end();
    });
  },
});

export default defineConfig({
  plugins: [react(), demoCache()],
  // Scan only the demo entries for dependencies (not the operator terminal's built dist/index.html).
  optimizeDeps: { entries: ["demo.html", "prep.html"] },
  // 127.0.0.1: uvicorn listens on IPv4 only, and "localhost" may resolve to ::1 first.
  server: { port: 5174, strictPort: true, proxy: { "/api": "http://127.0.0.1:8010" } },
  preview: { port: 5175, strictPort: true, proxy: {} },
  build: {
    outDir: "dist-demo",
    emptyOutDir: true,
    rollupOptions: { input: resolve(root, "demo.html") },
  },
});
