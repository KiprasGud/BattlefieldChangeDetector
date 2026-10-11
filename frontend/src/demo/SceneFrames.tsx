import type { CSSProperties } from "react";
import type { Change } from "../types";
import { targetId } from "../util";
import { sceneFile, type DemoScene } from "./scene";

// Side-by-side view of a cached scene: baseline | aligned recon, the AI boxes on both. Aligned B shares image A's
// frame, so one 0-1000 box marks the same ground in both. Same overlay as ResultViewer: the box layer takes the
// image's aspect ratio and is fitted like the letterboxed image (index.css .box-layer.fitted in a .fit-host).

interface FrameProps {
  src: string;
  label: string;
  recon?: boolean;
  changes: Change[];
  ratio: number;
  selected: number | null;
  onSelect: (index: number | null) => void;
}

function Frame({ src, label, recon, changes, ratio, selected, onSelect }: FrameProps) {
  return (
    <div className="fit-host present-frame" onClick={() => onSelect(null)}>
      <img className="diff-layer" src={src} alt={label} draggable={false} />
      <div className="box-layer fitted" style={{ position: "absolute", pointerEvents: "none", "--ar": ratio } as CSSProperties}>
        {changes.map((c, i) => {
          const [ymin, xmin, ymax, xmax] = c.box.map((v) => Math.max(0, Math.min(1000, v)) / 10);
          const state = selected === null ? "" : selected === i ? "selected" : "dimmed";
          return (
            <div
              key={i}
              className={`tactical-box ${recon ? "" : "present-ghost"} ${state}`}
              title={`${targetId(i)} ${c.type}`}
              style={{ top: `${ymin}%`, left: `${xmin}%`, width: `${xmax - xmin}%`, height: `${ymax - ymin}%` }}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(selected === i ? null : i);
              }}
            >
              <span className="tactical-box-label">[{targetId(i)}] {c.type}</span>
            </div>
          );
        })}
      </div>
      <div className={`diff-label ${recon ? "text-success" : ""}`}>{label}</div>
    </div>
  );
}

interface Props {
  scene: DemoScene;
  selected: number | null;
  onSelect: (index: number | null) => void;
}

export default function SceneFrames({ scene, selected, onSelect }: Props) {
  const shared = { changes: scene.result.changes, ratio: scene.size.w / scene.size.h, selected, onSelect };
  return (
    <div className="present-frames">
      <Frame src={sceneFile(scene, "image_a")} label="BASELINE · PAST" {...shared} />
      <Frame src={sceneFile(scene, "aligned_b")} label="RECON · PRESENT" recon {...shared} />
    </div>
  );
}
