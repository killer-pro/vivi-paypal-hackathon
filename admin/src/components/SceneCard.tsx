import { useState } from "react";
import type { ProjectDetail } from "../api";
import type { DraftScene } from "../plan";
import { sceneLink, type CastMember } from "../casting";
import AssistField from "./AssistField";
import { CastFrame } from "./CastStrip";
import SceneChips from "./SceneChips";
import { Field } from "./ui";
import TextArea from "./TextArea";
import { MAX_VISUAL_PROMPT } from "../limits";

interface Props {
  scene: DraftScene;
  index: number;
  count: number;
  project: ProjectDetail;
  locked: boolean;
  /** Le plan a des modifications non enregistrées (l'assistant le signale). */
  dirty: boolean;
  selected?: boolean;
  /** Bouton replier / déplier ; la carte est dépliée par défaut. */
  collapsible?: boolean;
  /** Casting du projet : la carte montre alors l'image de l'élément principal, les éléments visibles et l'enchaînement
   *  (d'après la scène enregistrée ; une scène ajoutée au brouillon n'en a pas encore). */
  cast?: CastMember[];
  onContinuity?: (sceneId: number, continuity: "cut" | "continue") => void;
  /** L'ordre du brouillon est celui enregistré : sinon l'enchaînement (relatif à la scène précédente enregistrée)
   *  serait faux, il est masqué jusqu'à l'enregistrement. */
  ordered?: boolean;
  onChange: (key: string, patch: Partial<DraftScene>) => void;
  onMove: (i: number, by: number) => void;
  onRemove: (i: number) => void;
}

/** Carte d'une scène du plan : voix off, prompt visuel, durée, avec leurs assistants IA ; avec le casting, sa vignette,
 *  ses éléments visibles et son enchaînement avec la précédente. */
export default function SceneCard({
  scene: s,
  index: i,
  count,
  project,
  locked,
  dirty,
  selected,
  collapsible,
  cast,
  onContinuity,
  ordered = true,
  onChange,
  onMove,
  onRemove,
}: Props) {
  const [open, setOpen] = useState(true);
  const shown = !collapsible || open;
  const at = project.scenes.findIndex((x) => x.id === s.id);
  const saved = project.scenes[at];
  const main = cast?.find((m) => m.id === saved?.reference);
  const chained = cast && ordered && sceneLink(project.scenes, at)?.kind === "chain";
  const classes = ["scene-card", selected && "is-selected", cast && "has-cast", chained && "is-chained"];
  return (
    <li className={classes.filter(Boolean).join(" ")} data-scene={s.id}>
      {cast && (
        <div className="scene-card-thumb">
          <CastFrame member={main} />
        </div>
      )}
      <div className="scene-card-head">
        <h3>Scène {i + 1}</h3>
        <div className="scene-card-tools">
          {collapsible && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              aria-expanded={open}
              onClick={() => setOpen(!open)}
            >
              {open ? "Replier" : "Déplier"}
            </button>
          )}
          <button type="button" className="btn btn-ghost btn-small" disabled={i === 0} onClick={() => onMove(i, -1)}>
            Monter
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            disabled={i === count - 1}
            onClick={() => onMove(i, 1)}
          >
            Descendre
          </button>
          <button type="button" className="btn btn-ghost btn-small" onClick={() => onRemove(i)}>
            Supprimer
          </button>
        </div>
      </div>
      {cast && saved && <SceneChips scene={saved} index={at} scenes={project.scenes} cast={cast} showLink={ordered} />}
      {saved && at > 0 && ordered && onContinuity && (
        <label className="scene-element" title="Sans la case, le clip part de l'image de référence de la scène">
          <input
            type="checkbox"
            checked={saved.continuity === "continue"}
            disabled={locked}
            onChange={(e) => onContinuity(saved.id, e.target.checked ? "continue" : "cut")}
          />
          Enchaîner avec la scène précédente
        </label>
      )}
      {!shown && <p className="muted scene-summary">{s.voice_text || "Scène vide"}</p>}
      {shown && (
        <div className="scene-fields">
          <AssistField
            label="Texte de la voix off"
            kind="voice_text"
            value={s.voice_text}
            onChange={(v) => onChange(s.key, { voice_text: v })}
            context={{ projectId: project.id, sceneId: s.id, durationS: s.duration_s }}
            scope={`scène ${i + 1}`}
            locked={locked}
            unsaved={dirty}
          >
            {(f) => (
              <TextArea
                {...f}
                className="input"
                required
                value={s.voice_text}
                onChange={(e) => onChange(s.key, { voice_text: e.target.value })}
              />
            )}
          </AssistField>
          <AssistField
            label="Prompt visuel"
            kind="visual_prompt"
            value={s.visual_prompt}
            onChange={(v) => onChange(s.key, { visual_prompt: v })}
            context={{ projectId: project.id, sceneId: s.id }}
            scope={`scène ${i + 1}`}
            locked={locked}
            unsaved={dirty}
          >
            {(f) => (
              <TextArea
                {...f}
                className="input"
                required
                maxLength={MAX_VISUAL_PROMPT}
                value={s.visual_prompt}
                onChange={(e) => onChange(s.key, { visual_prompt: e.target.value })}
              />
            )}
          </AssistField>
          <Field label="Durée (s)">
            <input
              className="input input-narrow"
              type="number"
              required
              min={0.5}
              step={0.5}
              value={s.duration_s}
              onChange={(e) => onChange(s.key, { duration_s: e.target.valueAsNumber })}
            />
          </Field>
        </div>
      )}
    </li>
  );
}
