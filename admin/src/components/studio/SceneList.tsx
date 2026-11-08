import { useEffect, useRef, type ReactNode } from "react";
import { latestAsset, type ProjectDetail } from "../../api";
import { castOf, sceneLink } from "../../casting";
import { clock } from "../../format";
import type { Activity } from "../../studio";
import { ChevronDownIcon, ChevronUpIcon } from "../icons";
import SceneChips from "../SceneChips";
import { t } from "../../i18n";

/** Vrai si la scène d'indice `i` part de la dernière image de la précédente. */
const chainedAt = (scenes: ProjectDetail["scenes"], i: number) => sceneLink(scenes, i)?.kind === "chain";

/** Storyboard : une ligne par scène (vignette, texte dit, durée, présence du clip et de la voix, éléments visibles) ; un
 *  trait d'accent dans la marge relie les scènes enchaînées. */
export default function SceneList({
  project,
  index,
  onSelect,
  onMove,
  locked,
  generating,
  collapsed,
  children,
}: {
  project: ProjectDetail;
  index: number;
  onSelect: (index: number) => void;
  /** Déplace la scène sélectionnée d'un rang. */
  onMove: (delta: -1 | 1) => void;
  /** Génération en cours ou action en attente : l'ordre ne peut pas changer. */
  locked: boolean;
  /** Générations en cours : la scène visée par l'une d'elles porte une pastille. */
  generating: Activity[];
  collapsed: boolean;
  /** Bord de la colonne (poignée de largeur et bouton de repliage). */
  children: ReactNode;
}) {
  const list = useRef<HTMLOListElement>(null);
  const cast = castOf(project);
  // La scène choisie ailleurs (aperçu, timeline, flèches) reste visible dans la liste.
  useEffect(() => {
    list.current?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [index]);

  return (
    <nav className={collapsed ? "scene-rail is-collapsed" : "scene-rail"} aria-label={t("Scènes")}>
      {children}
      <div className="scene-rail-body" inert={collapsed}>
        <h2>{t("Scènes ({n})", { n: project.scenes.length })}</h2>
        <ol ref={list}>
          {project.scenes.map((scene, i) => {
            const clip = project.assets.find((a) => a.id === scene.selected_clip_asset_id);
            const voice = latestAsset(project.assets, "voice", scene.id);
            const busy = generating.find((a) => a.sceneId === scene.id);
            const chained = chainedAt(project.scenes, i);
            const classes = [chained && "is-chained", chainedAt(project.scenes, i + 1) && "chains-next"];
            return (
              <li key={scene.id} className={classes.filter(Boolean).join(" ") || undefined}>
                <button
                  className="scene-item"
                  aria-current={i === index ? "true" : undefined}
                  data-scene-block
                  onClick={() => onSelect(i)}
                >
                  <span className="scene-thumb">
                    {clip && <video src={`${clip.url}#t=0.5`} muted preload="metadata" tabIndex={-1} />}
                    <span className="tl-num">{scene.position}</span>
                    {busy && (
                      <>
                        <span className="scene-busy" aria-hidden />
                        <span className="sr-only">{busy.label} en cours</span>
                      </>
                    )}
                  </span>
                  <span className="scene-text">{scene.voice_text || t("Scène sans texte")}</span>
                  <span className="scene-flags">
                    <span className="scene-duration">{clock(scene.duration_s)}</span>
                    <span className={clip ? "flag lane-clip is-on" : "flag lane-clip"}>
                      {t("Clip")}{!clip && <span className="sr-only"> {t("manquant")}</span>}
                    </span>
                    <span className={voice ? "flag lane-voice is-on" : "flag lane-voice"}>
                      {t("Voix")}{!voice && <span className="sr-only"> {t("manquante")}</span>}
                    </span>
                  </span>
                </button>
                {/* Hors du bouton (qui n'admet pas de liste) ; seul l'enchaînement est écrit, une coupe se lit à l'absence de trait. */}
                <SceneChips scene={scene} index={i} scenes={project.scenes} cast={cast} showLink={chained} />
                {i === index && project.scenes.length > 1 && (
                  <div className="scene-move">
                    <button
                      className="btn btn-small btn-ghost"
                      disabled={locked || i === 0}
                      onClick={() => onMove(-1)}
                      title={t("Monter la scène")}
                    >
                      <ChevronUpIcon /> {t("Monter")}
                    </button>
                    <button
                      className="btn btn-small btn-ghost"
                      disabled={locked || i === project.scenes.length - 1}
                      onClick={() => onMove(1)}
                      title={t("Descendre la scène")}
                    >
                      <ChevronDownIcon /> {t("Descendre")}
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </nav>
  );
}
