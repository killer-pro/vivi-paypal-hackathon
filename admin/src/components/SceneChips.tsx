import type { Scene } from "../api";
import { sceneElements, sceneLink, type CastMember } from "../casting";
import { ELEMENT_KINDS } from "../story";
import "./Cast.css";

/** Éléments visibles d'une scène (avec leur état) puis son enchaînement avec la précédente. */
export default function SceneChips({
  scene,
  index,
  scenes,
  cast,
  showLink = true,
}: {
  scene: Pick<Scene, "elements">;
  index: number;
  scenes: Pick<Scene, "position" | "continuity">[];
  cast: CastMember[];
  /** `false` : pas de ligne d'enchaînement (ex. ordre du brouillon différent de l'ordre enregistré). */
  showLink?: boolean;
}) {
  const elements = sceneElements(scene, cast);
  const link = showLink ? sceneLink(scenes, index) : null;
  if (!elements.length && !link) return null;
  return (
    <div className="scene-chips">
      {elements.length > 0 && (
        <ul className="cast-chips" aria-label="Éléments visibles">
          {elements.map(({ member, state }) => (
            <li key={member.id} className="cast-chip" title={ELEMENT_KINDS[member.kind]}>
              <span>{member.name}</span>
              {state && <span className="muted">{state}</span>}
            </li>
          ))}
        </ul>
      )}
      {link && (
        <p className={`scene-link is-${link.kind}`}>
          {link.kind === "chain" ? `Enchaînée : part de la dernière image de la scène ${link.from}` : "Coupe"}
        </p>
      )}
    </div>
  );
}
