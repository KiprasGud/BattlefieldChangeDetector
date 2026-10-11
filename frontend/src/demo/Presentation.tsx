import { useEffect, useState } from "react";
import { CATEGORY_LABELS } from "../types";
import { pad2, targetId } from "../util";
import SceneFrames from "./SceneFrames";
import { loadScenes, preloadImages, sceneFile, type DemoScene } from "./scene";

// Audience view (docs/demo.md). Plays the scenes cached in prep mode, read as static files from /demo_cache: no API
// call, no system log, warnings, timings, settings or heatmap. Index 0 is the title card, scenes are 1..n; the
// index is kept in the URL hash, so a reload stays on the same scene.

const indexFromHash = () => {
  const n = Number.parseInt(window.location.hash.slice(1), 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
};

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
  else document.documentElement.requestFullscreen().catch(() => undefined);
}

export default function Presentation() {
  const [scenes, setScenes] = useState<DemoScene[] | null>(null);
  const [index, setIndex] = useState(indexFromHash);
  const [selected, setSelected] = useState<number | null>(null);
  const [light, setLight] = useState(false);

  useEffect(() => {
    let alive = true;
    loadScenes().then((list) => {
      if (!alive) return;
      setScenes(list);
      setIndex((i) => Math.min(i, list.length));
      // Decode every scene's images while the title card is up.
      preloadImages(list.flatMap((s) => [sceneFile(s, "image_a"), sceneFile(s, "aligned_b")]));
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    document.body.className = light ? "theme-light" : "";
  }, [light]);

  useEffect(() => {
    if (scenes) window.history.replaceState(null, "", index ? `#${index}` : window.location.pathname);
  }, [index, scenes]);

  const count = scenes?.length ?? 0;
  const scene = scenes && index > 0 ? scenes[index - 1] ?? null : null;
  const changes = scene?.result.changes ?? [];

  const go = (next: number) => {
    setIndex(Math.max(0, Math.min(count, next)));
    setSelected(null);
  };

  const start = () => {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => undefined);
    go(1);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) return;
      if (e.altKey) {
        if (e.key.toLowerCase() === "s") {
          e.preventDefault();
          setLight((v) => !v);
        }
        return;
      }
      switch (e.key) {
        case "ArrowRight":
        case "PageDown": // presenter remotes send PageUp / PageDown
        case " ":
          go(index + 1);
          break;
        case "ArrowLeft":
        case "PageUp":
          go(index - 1);
          break;
        case "Home":
          go(0);
          break;
        case "End":
          go(count);
          break;
        case "Enter":
          if (index !== 0) return;
          start();
          break;
        case "ArrowDown":
        case "ArrowUp": {
          if (!changes.length) return;
          const step = e.key === "ArrowDown" ? 1 : -1;
          setSelected((i) =>
            i === null ? (step > 0 ? 0 : changes.length - 1) : Math.max(0, Math.min(changes.length - 1, i + step))
          );
          break;
        }
        case "Escape":
          setSelected(null);
          return; // leave the browser's own Esc (exit fullscreen) alone
        case "f":
        case "F":
          toggleFullscreen();
          break;
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const footer = (
    <footer className="present-foot mono">
      <span>[←/→] SCENE</span>
      {scene && <span>[↑/↓] TARGET</span>}
      <span>[F] FULLSCREEN</span>
      <span>[ALT+S] {light ? "DARK" : "LIGHT"}</span>
      <span className="spacer" />
      {scene?.source === "gemini" && (
        <span>
          AI: {(scene.model ?? "gemini").toUpperCase()} · ANALYZED {scene.result.report_date}
        </span>
      )}
    </footer>
  );

  if (scenes === null) return <div className="present" />; // reading the cache: a few milliseconds

  if (!count) {
    return (
      <div className="present present-empty">
        <div className="pane-title">NO CACHED SCENES</div>
        <div className="text-dim">Run prep mode (demo.ps1 prep) and press CACHE STATE.</div>
      </div>
    );
  }

  if (!scene) {
    return (
      <div className="present">
        <div />
        <div className="present-cover">
          <div className="pane-title text-success">ŽVALGAS AI</div>
          <h1 className="present-cover-title">BATTLEFIELD CHANGE DETECTION</h1>
          <div className="present-cover-sub text-dim">Past vs. present drone imagery · OpenCV aligns, AI detects</div>
          <div className="present-agenda">
            {scenes.map((s, i) => (
              <button key={s.id} className="target-row" onClick={() => go(i + 1)}>
                <span className="mono">{pad2(i + 1)}</span>
                <span className="target-row-label">
                  {s.title}
                  {s.subtitle && <span className="text-dim"> — {s.subtitle}</span>}
                </span>
              </button>
            ))}
          </div>
          <button className="btn-exec present-start" onClick={start}>
            <span>LAUNCH PRESENTATION</span>
            <span className="shortcut-key">[ENTER]</span>
          </button>
        </div>
        {footer}
      </div>
    );
  }

  const target = selected !== null ? changes[selected] ?? null : null;
  const n = changes.length;

  return (
    <div className="present">
      <header className="present-head">
        <div className="pane-title text-success">ŽVALGAS AI // CHANGE DETECTION</div>
        <div className="present-title">
          <span className="mono text-dim">
            SCENE {pad2(index)}/{pad2(count)}
          </span>
          <span className="present-title-main">{scene.title}</span>
          {scene.subtitle && <span className="present-title-sub text-dim">{scene.subtitle}</span>}
        </div>
      </header>

      <main className="present-stage">
        <SceneFrames scene={scene} selected={selected} onSelect={setSelected} />

        <aside className="present-side">
          <div className="present-count">
            <span className="mono">{n || "NO"}</span> {n === 1 ? "CHANGE" : "CHANGES"} DETECTED
          </div>

          <div className="control-group">
            <div className="control-label">TASKING</div>
            <div>{scene.criteria}</div>
          </div>

          {n > 0 && (
            <div className="control-group">
              <div className="control-label">TARGETS</div>
              <div className="target-list present-targets">
                {changes.map((c, i) => (
                  <button
                    key={i}
                    className={`target-row ${selected === i ? "active" : ""}`}
                    onClick={() => setSelected(selected === i ? null : i)}
                  >
                    <span className="mono">{targetId(i)}</span>
                    <span className="target-row-label">{c.type}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {target && (
            <div className="present-detail">
              <div className="mono">
                {targetId(selected!)} · {target.confidence.toUpperCase()}
                {target.sector ? ` · SECTOR ${target.sector}` : ""}
              </div>
              {target.category && <div className="text-dim">{CATEGORY_LABELS[target.category]}</div>}
              <div>{target.description}</div>
              {target.location_text && <div className="text-dim">{target.location_text}</div>}
            </div>
          )}

          <div className="control-group">
            <div className="control-label">ASSESSMENT</div>
            <div>{scene.result.summary}</div>
          </div>

          <div className="control-group">
            <div className="control-label">RECOMMENDATION</div>
            <div>{scene.result.recommendation}</div>
          </div>
        </aside>
      </main>

      {footer}
    </div>
  );
}
