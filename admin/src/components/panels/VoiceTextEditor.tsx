import type { FormEvent } from "react";
import type { Scene } from "../../api";
import { useDraft } from "../../hooks/useDraft";
import type { Flow } from "../../hooks/useProject";
import AssistField from "../AssistField";
import TextArea from "../TextArea";
import { FormActions } from "../ui";
import { t } from "../../i18n";

/** Texte prononcé (et sous-titré) d'une scène. Enregistré, il périme la voix de la scène : à régénérer. */
export default function VoiceTextEditor({
  flow,
  scene,
  projectId,
  locked,
  hasVoice,
}: {
  flow: Flow;
  scene: Scene;
  projectId: number;
  locked: boolean;
  hasVoice: boolean;
}) {
  const text = useDraft(scene.voice_text);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (await flow.setVoiceText(scene.id, text.value.trim())) text.reset();
  }

  return (
    <form className="form" onSubmit={save}>
      <AssistField
        label={t("Texte de la voix off")}
        kind="voice_text"
        value={text.value}
        onChange={(v) => text.update(() => v)}
        context={{ projectId, sceneId: scene.id, durationS: scene.duration_s }}
        scope={t("scène {n}", { n: scene.position })}
        locked={locked}
        unsaved={text.dirty}
      >
        {(f) => (
          <TextArea {...f} className="input" required value={text.value} onChange={(e) => text.set(e.target.value)} />
        )}
      </AssistField>
      {text.dirty && (
        <>
          {hasVoice && (
            <p className="muted">{t("La voix actuelle garde l'ancien texte : régénérez-la après l'enregistrement.")}</p>
          )}
          <FormActions submitLabel={t("Enregistrer le texte")} onCancel={text.reset} disabled={locked || !text.value.trim()} />
        </>
      )}
    </form>
  );
}
