import type { FormEvent } from "react";
import type { ProjectIn } from "../../api";
import { useDraft } from "../../hooks/useDraft";
import { hasResult } from "../../steps";
import AssistField from "../AssistField";
import ProjectFields from "../ProjectFields";
import StepPanel, { type PanelProps } from "../StepPanel";
import TextArea from "../TextArea";
import { Advanced, FormActions } from "../ui";
import { t } from "../../i18n";

export default function IdeaPanel(props: PanelProps) {
  const { flow, project, step, locked } = props;
  const { title, theme, platform, target_duration_s } = project;
  const brief = useDraft<ProjectIn>({ title, theme, platform, target_duration_s });
  const hint = useDraft(String(step.params.hint ?? ""));
  const angle = useDraft(String(step.result?.angle ?? ""));
  const assist = { context: { projectId: project.id }, locked };
  // Idée validée : seuls le titre et le format restent utiles ; piste de départ et angle se replient ou disparaissent.
  const settled = step.status === "approved";

  async function saveBrief(e: FormEvent) {
    e.preventDefault();
    if (await flow.updateProject(brief.value)) brief.reset();
  }

  async function saveAngle(e: FormEvent) {
    e.preventDefault();
    if (await flow.patch("idea", { result: { ...step.result, angle: angle.value } })) angle.reset();
  }

  const angleForm = (
    <form className="form" onSubmit={saveAngle}>
      <AssistField label={t("Angle proposé")} kind="angle" value={angle.value} onChange={angle.set} unsaved={angle.dirty} {...assist}>
        {(f) => <TextArea {...f} className="input input-tall" value={angle.value} onChange={(e) => angle.set(e.target.value)} />}
      </AssistField>
      {angle.dirty && <FormActions submitLabel={t("Enregistrer l'angle")} onCancel={angle.reset} disabled={locked} />}
    </form>
  );

  return (
    <StepPanel
      {...props}
      runLabel={t("Développer l'angle")}
      hideRun={settled}
      onRun={() => flow.run("idea", undefined, { params: { hint: hint.value } })}
    >
      <form className="form panel-section" onSubmit={saveBrief}>
        <h3>{t("Brief")}</h3>
        <ProjectFields
          value={brief.value}
          onChange={brief.update}
          projectId={project.id}
          locked={locked}
          unsaved={brief.dirty}
          foldTheme={settled}
        />
        {brief.dirty && <FormActions submitLabel={t("Enregistrer le brief")} onCancel={brief.reset} disabled={locked} />}
      </form>

      {!settled && (
        <div className="form panel-section">
          <AssistField label={t("Piste de départ (facultatif)")} kind="hint" value={hint.value} onChange={hint.set} unsaved={hint.dirty} {...assist}>
            {(f) => (
              <TextArea
                {...f}
                className="input"
                placeholder={t("Ex. partir d'une erreur que tout le monde fait")}
                value={hint.value}
                onChange={(e) => hint.set(e.target.value)}
              />
            )}
          </AssistField>
        </div>
      )}

      {hasResult(step) && (settled ? <Advanced label={t("Angle retenu")}>{angleForm}</Advanced> : <div className="panel-section">{angleForm}</div>)}
    </StepPanel>
  );
}
