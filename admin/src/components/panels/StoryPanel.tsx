import { useState, type FormEvent } from "react";
import { useStoryDraft } from "../../hooks/useStoryDraft";
import { useApi } from "../../api";
import { parseVoices } from "../../settings";
import { hasResult } from "../../steps";
import StoryView from "../plan/StoryView";
import StepPanel, { type PanelProps } from "../StepPanel";
import TextArea from "../TextArea";
import { Field } from "../ui";
import { t } from "../../i18n";

/** Étape Histoire dans l'éditeur : les mêmes beats et éléments que l'écran Plan. */
export default function StoryPanel(props: PanelProps) {
  const { flow, project, step, locked } = props;
  const draft = useStoryDraft(step);
  const [instruction, setInstruction] = useState("");
  const voices = parseVoices(useApi<Record<string, string>>("/settings/editor").data?.voice_catalog);
  const warnings = Array.isArray(step.result?.warnings) ? (step.result.warnings as string[]) : [];

  function save(e: FormEvent) {
    e.preventDefault();
    void draft.save(flow);
  }

  return (
    <StepPanel
      {...props}
      runLabel={hasResult(step) ? t("Réécrire l'histoire") : t("Écrire l'histoire")}
      onRun={() =>
        flow.run("story", undefined, { overrides: instruction.trim() ? { instruction: instruction.trim() } : undefined })
      }
      runBlocked={draft.dirty ? t("Enregistrez ou annulez vos modifications avant de réécrire l'histoire.") : undefined}
      confirmRun={t("L'histoire actuelle sera remplacée : les scènes écrites à partir d'elle deviendront périmées.")}
    >
      <Field label={t("Consigne pour réécrire l'histoire (facultatif)")}>
        <TextArea
          className="input"
          rows={2}
          maxLength={1000}
          placeholder={t("Ex. : plus d'action, ajoute le logo Coca-Cola dès le premier beat, ton plus humoristique.")}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
        />
      </Field>
      <StoryView
        draft={draft}
        warnings={warnings}
        locked={locked}
        voices={voices}
        targetS={project.target_duration_s}
        onSave={save}
      />
    </StepPanel>
  );
}
