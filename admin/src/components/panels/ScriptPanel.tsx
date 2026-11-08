import { useEffect, useRef, useState, type FormEvent } from "react";
import { castOf } from "../../casting";
import { usePlanDraft } from "../../hooks/usePlanDraft";
import { hasResult } from "../../steps";
import AssistField from "../AssistField";
import CastStrip from "../CastStrip";
import SceneCard from "../SceneCard";
import StepPanel, { type PanelProps } from "../StepPanel";
import { Field, FormActions } from "../ui";
import TextArea from "../TextArea";
import { locale, t, tn } from "../../i18n";

export default function ScriptPanel(props: PanelProps) {
  const { flow, project, step, locked, scene } = props;
  const listRef = useRef<HTMLOListElement>(null);
  const draft = usePlanDraft(project, step);
  const { list, bible, dirty, total, blank, ordered } = draft;
  const cast = castOf(project);
  const [instruction, setInstruction] = useState("");

  // Scène choisie dans la timeline : mise en évidence et amenée à l'écran.
  useEffect(() => {
    if (scene) listRef.current?.querySelector(`[data-scene="${scene.id}"]`)?.scrollIntoView({ block: "nearest" });
  }, [scene]);

  function save(e: FormEvent) {
    e.preventDefault();
    void draft.save(flow);
  }

  return (
    <StepPanel
      {...props}
      runLabel={hasResult(step) ? t("Régénérer le script") : t("Générer le script")}
      onRun={() =>
        flow.run("script", undefined, { overrides: instruction.trim() ? { instruction: instruction.trim() } : undefined })
      }
      runBlocked={
        dirty ? t("Enregistrez ou annulez vos modifications avant de générer un nouveau script.") : undefined
      }
      confirmRun={t("Le script actuel sera remplacé par un nouveau découpage : les scènes, leurs textes et les clips choisis pour le montage seront perdus.")}
    >
      <form className="form" onSubmit={save}>
        <CastStrip cast={cast} flow={flow} />
        <p className="muted">
          {tn(list.length, "{n} scène", "{n} scènes")}, {total.toLocaleString(locale)} s {t("sur")} {project.target_duration_s} s {t("visées")}
        </p>
        <AssistField
          label={t("Fiche visuelle (personnages, marques, décor, style)")}
          kind="bible"
          value={bible.value}
          onChange={bible.set}
          context={{ projectId: project.id }}
          scope="fiche visuelle"
          locked={locked}
          unsaved={dirty}
        >
          {(f) => (
            <TextArea
              {...f}
              className="input"
              rows={6}
              placeholder={t("Rédigée par l'IA au moment du script : elle fixe l'apparence des personnages et des marques, que chaque prompt visuel reprend à l'identique.")}
              value={bible.value}
              onChange={(e) => bible.set(e.target.value)}
            />
          )}
        </AssistField>
        <Field label={t("Consigne pour régénérer le plan (facultatif)")}>
          <TextArea
            className="input"
            rows={2}
            maxLength={1000}
            placeholder={t("Ex. : plus d'action, ajoute le logo Coca-Cola dès la première scène, ton plus humoristique.")}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
          />
        </Field>
        <ol className="scene-list" ref={listRef}>
          {list.map((s, i) => (
            <SceneCard
              key={s.key}
              scene={s}
              index={i}
              count={list.length}
              project={project}
              locked={locked}
              dirty={dirty}
              selected={s.id !== undefined && s.id === scene?.id}
              cast={cast}
              onContinuity={flow.setSceneContinuity}
              ordered={ordered}
              onChange={draft.update}
              onMove={draft.move}
              onRemove={draft.remove}
            />
          ))}
        </ol>
        <div>
          <button type="button" className="btn" onClick={draft.add}>
            {t("Ajouter une scène")}
          </button>
        </div>
        {dirty && blank >= 0 && (
          <p className="error" role="alert">
            Scène {blank + 1} : le texte de la voix off et le prompt visuel sont obligatoires.
          </p>
        )}
        {dirty && (
          <FormActions
            submitLabel={t("Enregistrer le plan")}
            onCancel={draft.reset}
            disabled={locked || blank >= 0}
          />
        )}
      </form>
    </StepPanel>
  );
}
