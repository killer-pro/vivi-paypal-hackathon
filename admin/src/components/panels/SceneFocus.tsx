import type { ReactNode } from "react";
import type { Scene } from "../../api";

/** Scène sélectionnée dans la timeline, dans un panneau qui travaille scène par scène (clips, voix). */
export default function SceneFocus({
  scene,
  count,
  hideText = false,
  children,
}: {
  scene: Scene | null;
  count: number;
  /** Le panneau affiche déjà le texte de la scène (ex. pour le modifier). */
  hideText?: boolean;
  children: ReactNode;
}) {
  if (!scene) return <p className="empty-line">Aucune scène : générez d'abord le script.</p>;
  return (
    <section className="scene-focus" aria-label={`Scène ${scene.position}`}>
      <header className="scene-focus-head">
        <h3>
          Scène {scene.position} <span className="muted">sur {count}</span>
        </h3>
        {!hideText && <p className="muted">{scene.voice_text}</p>}
      </header>
      {children}
    </section>
  );
}
