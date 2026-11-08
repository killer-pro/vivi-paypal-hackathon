import type { ChangeEvent, FormEvent } from "react";
import { useDraft } from "../../hooks/useDraft";
import { hasResult } from "../../steps";
import AssistField from "../AssistField";
import StepPanel, { type PanelProps } from "../StepPanel";
import { FormActions } from "../ui";
import TextArea from "../TextArea";
import { t } from "../../i18n";

export default function FinalPanel(props: PanelProps) {
  const { flow, project, step, locked } = props;
  const result = step.result ?? {};
  const meta = useDraft({
    title: String(result.title ?? ""),
    description: String(result.description ?? ""),
    hashtags: ((result.hashtags as string[] | undefined) ?? []).join(" "),
  });
  type Key = keyof typeof meta.value;
  // Mise à jour fonctionnelle : une réponse tardive de l'assistant n'écrase pas les autres champs saisis entre-temps.
  const set = (key: Key, v: string) => meta.update((prev) => ({ ...prev, [key]: v }));
  const change = (key: Key) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(key, e.target.value);
  // Props communes des champs avec assistant IA.
  const field = (key: Key) => ({
    value: meta.value[key],
    onChange: (v: string) => set(key, v),
    context: { projectId: project.id },
    locked,
    unsaved: meta.dirty,
  });

  async function save(e: FormEvent) {
    e.preventDefault();
    const { title, description, hashtags } = meta.value;
    if (await flow.patch("final", { result: { title, description, hashtags: hashtags.split(/\s+/).filter(Boolean) } }))
      meta.reset();
  }

  return (
    <StepPanel
      {...props}
      runLabel={hasResult(step) ? t("Régénérer les métadonnées") : t("Générer les métadonnées")}
      approveLabel={t("Valider le projet")}
    >
      {hasResult(step) ? (
        <form className="form" onSubmit={save}>
          <AssistField label={t("Titre de publication")} kind="title" {...field("title")}>
            {(f) => <input {...f} className="input" value={meta.value.title} onChange={change("title")} />}
          </AssistField>
          <AssistField label={t("Description")} kind="description" {...field("description")}>
            {(f) => (
              <TextArea
                {...f}
                className="input input-tall"
                value={meta.value.description}
                onChange={change("description")}
              />
            )}
          </AssistField>
          <AssistField label={t("Hashtags (séparés par des espaces)")} kind="hashtags" {...field("hashtags")}>
            {(f) => <input {...f} className="input" value={meta.value.hashtags} onChange={change("hashtags")} />}
          </AssistField>
          {meta.dirty && <FormActions submitLabel={t("Enregistrer")} onCancel={meta.reset} disabled={locked} />}
        </form>
      ) : null}
    </StepPanel>
  );
}
