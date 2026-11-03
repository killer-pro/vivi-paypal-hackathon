import type { Scene } from "../../api";
import { clock } from "../../format";
import type { Player } from "../../hooks/usePlayer";
import { MicIcon, PauseIcon, PlayIcon, RefreshIcon } from "../icons";

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
  const caption = render ? "Rendu final" : scene ? `Scène ${scene.position}` : "Aperçu";
  return (
    <main className="preview" aria-label="Aperçu">
      <div className="preview-frame">
        {src ? (
          <video
            ref={video}
            src={src}
            playsInline
            preload="auto"
            muted={!render} // les clips sont muets : la voix joue à côté
            onClick={toggle}
            aria-label={render ? "Rendu de la vidéo" : `Clip de la scène ${scene?.position}`}
            {...handlers}
          />
        ) : (
          <p className="preview-empty">
            {scene ? `Pas encore de clip pour la scène ${scene.position}.` : "L'aperçu apparaît dès que les clips sont générés."}
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
          aria-label={playing ? "Pause (espace)" : "Lecture (espace)"}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <span className="transport-time">
          {clock(time)} <span className="muted">/ {clock(total)}</span>
        </span>
        <span className="transport-caption muted">{caption}</span>
      </div>
      {scene && (
        <div className="scene-actions" role="group" aria-label={`Modifier la scène ${scene.position}`}>
          <button className="btn" onClick={onEditClip}>
            <RefreshIcon />
            <span>
              Régénérer le clip<span className="hide-narrow"> de la scène {scene.position}</span>
            </span>
          </button>
          <button className="btn" onClick={onEditVoice}>
            <MicIcon /> Régénérer la voix
          </button>
        </div>
      )}
    </main>
  );
}
