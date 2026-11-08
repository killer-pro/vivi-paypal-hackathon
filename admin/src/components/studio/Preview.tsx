import type { Scene } from "../../api";
import { clock } from "../../format";
import type { Player } from "../../hooks/usePlayer";
import { MicIcon, PauseIcon, PlayIcon, RefreshIcon } from "../icons";
import { t } from "../../i18n";

/** Aperçu 9:16 : le rendu final s'il existe, sinon le clip choisi de la scène avec sa voix et son texte en sous-titre. */
export default function Preview({
  player,
  render,
  clip,
  voice,
  music,
  scene,
  total,
  onEditClip,
  onEditVoice,
}: {
  player: Player;
  render?: string;
  clip?: string;
  voice?: string;
  /** Musique de fond choisie (sans rendu : elle est mixée dans le rendu). */
  music?: string;
  scene: Scene | null;
  total: number;
  /** Ouvre l'étape Clips sur la scène, prompt à préciser. */
  onEditClip: () => void;
  /** Ouvre l'étape Voix sur la scène. */
  onEditVoice: () => void;
}) {
  const { video, audio, musicAudio, playing, time, toggle, handlers } = player;
  const src = render ?? clip;
  const caption = render ? t("Rendu final") : scene ? t("Scène {n}", { n: scene.position }) : t("Aperçu");
  return (
    <main className="preview" aria-label={t("Aperçu")}>
      <div className="preview-frame">
        {src ? (
          <video
            ref={video}
            src={src}
            playsInline
            preload="auto"
            muted={!render} // les clips sont muets : la voix joue à côté
            onClick={toggle}
            aria-label={render ? t("Rendu de la vidéo") : t("Clip de la scène {n}", { n: scene?.position ?? "" })}
            {...handlers}
          />
        ) : (
          <p className="preview-empty">
            {scene ? t("Pas encore de clip pour la scène {n}.", { n: scene.position }) : t("L'aperçu apparaît dès que les clips sont générés.")}
          </p>
        )}
        {!render && voice && <audio ref={audio} src={voice} preload="auto" />}
        {!render && music && <audio ref={musicAudio} src={music} loop preload="auto" />}
        {!render && scene && <p className="preview-subtitle">{scene.voice_text}</p>}
      </div>
      <div className="transport">
        <button
          className="play"
          onClick={toggle}
          disabled={!src}
          aria-label={playing ? t("Pause (espace)") : t("Lecture (espace)")}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <span className="transport-time">
          {clock(time)} <span className="muted">/ {clock(total)}</span>
        </span>
        <span className="transport-caption muted">{caption}</span>
      </div>
      {scene && (
        <div className="scene-actions" role="group" aria-label={t("Modifier la scène {n}", { n: scene.position })}>
          <button className="btn" onClick={onEditClip}>
            <RefreshIcon />
            <span>
              {t("Régénérer le clip")}<span className="hide-narrow"> {t("de la scène {n}", { n: scene.position })}</span>
            </span>
          </button>
          <button className="btn" onClick={onEditVoice}>
            <MicIcon /> {t("Régénérer la voix")}
          </button>
        </div>
      )}
    </main>
  );
}
