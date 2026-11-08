import type { CSSProperties, MouseEvent, ReactNode } from "react";
import { latestAsset, type ProjectDetail } from "../../api";
import { clock } from "../../format";
import { PlusIcon } from "../icons";
import type { StepName } from "../../steps";
import { laneState, rulerTicks, shortText, type Block, type LaneState } from "../../studio";
import { t } from "../../i18n";

interface TimelineProps {
  project: ProjectDetail;
  blocks: Block[];
  total: number;
  index: number;
  time: number;
  musicName: string | null;
  onSelect: (index: number) => void;
  onSeek: (t: number) => void;
  /** Bloc vide : choisir la scène et ouvrir l'étape qui le remplit. */
  onFill: (step: StepName, index: number) => void;
}

const pct = (n: number) => `${n}%`;

const STATE_SUFFIX: Record<LaneState, string> = { ready: "", generating: t(" : en génération"), empty: t(" : à générer") };

/** Timeline : règle de temps, pistes Clips, Voix et Musique, tête de lecture. Un bloc par scène, largeur ∝ durée. */
export default function Timeline({ project, blocks, total, index, time, musicName, onSelect, onSeek, onFill }: TimelineProps) {
  const running = (name: string) => project.steps.some((s) => s.name === name && s.status === "running");
  const clipsRunning = running("clips");
  const voiceRunning = running("voice");

  if (blocks.length === 0) return null;

  const seekFromRuler = (e: MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    onSeek(((e.clientX - rect.left) / rect.width) * total);
  };

  /** Bloc de scène : prêt (cliquable), en génération (rayé) ou vide (pointillé « + », ouvre l'outil). */
  const block = (i: number, step: StepName, state: LaneState, label: string, children: ReactNode) => {
    const b = blocks[i];
    const style = { left: pct(b.left), width: pct(b.width) } as CSSProperties;
    const empty = state === "empty";
    return (
      <button
        key={project.scenes[i].id}
        className={`tl-block is-${state}`}
        style={style}
        aria-current={i === index ? "true" : undefined}
        aria-label={`${label}${STATE_SUFFIX[state]}`}
        data-scene-block
        onClick={() => (empty ? onFill(step, i) : onSelect(i))}
      >
        {empty ? <PlusIcon /> : children}
      </button>
    );
  };

  return (
    <section className="timeline" aria-label={t("Timeline")} style={{ "--total-s": total } as CSSProperties}>
      <div className="tl-heads" aria-hidden>
        <span className="tl-head-ruler" />
        <span className="tl-head lane-clip">{t("Clips")}</span>
        <span className="tl-head lane-voice">{t("Voix")}</span>
        <span className="tl-head lane-music">{t("Musique")}</span>
      </div>
      <div className="tl-scroll">
        <div className="tl-tracks">
          <div className="tl-ruler" onClick={seekFromRuler} aria-hidden>
            {rulerTicks(total).map(({ t, label }) => (
              <span key={t} className={label ? "tick is-major" : "tick"} style={{ left: pct((t / total) * 100) }}>
                {label && clock(t)}
              </span>
            ))}
          </div>

          <div className="tl-lane lane-clip">
            {project.scenes.map((scene, i) => {
              const clip = project.assets.find((a) => a.id === scene.selected_clip_asset_id);
              return block(
                i,
                "clips",
                laneState(Boolean(clip), clipsRunning),
                t("Scène {n}, clip", { n: scene.position }),
                <>
                  {clip && <video className="tl-thumb" src={`${clip.url}#t=0.5`} muted preload="metadata" tabIndex={-1} />}
                  <span className="tl-num">{scene.position}</span>
                </>,
              );
            })}
          </div>

          <div className="tl-lane lane-voice">
            {project.scenes.map((scene, i) =>
              block(
                i,
                "voice",
                laneState(Boolean(latestAsset(project.assets, "voice", scene.id)), voiceRunning),
                t("{text} (scène {n}, voix)", { text: shortText(scene.voice_text), n: scene.position }),
                <span className="tl-text">{shortText(scene.voice_text)}</span>,
              ),
            )}
          </div>

          <div className="tl-lane lane-music">
            {musicName ? (
              <span className="tl-block tl-music is-ready" style={{ left: 0, width: "100%" }}>
                <span className="tl-text">{musicName}</span>
              </span>
            ) : (
              <span className="tl-none">{t("Sans musique")}</span>
            )}
          </div>

          <span className="tl-playhead" style={{ left: pct(Math.min(time / total, 1) * 100) }} aria-hidden />
        </div>
      </div>
    </section>
  );
}
