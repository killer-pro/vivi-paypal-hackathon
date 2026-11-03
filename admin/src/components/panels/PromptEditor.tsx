import type { ReactNode } from "react";
import type { AssistContext, AssistKind } from "../../assist";
import AssistField from "../AssistField";
import TextArea from "../TextArea";
import { MAX_VISUAL_PROMPT } from "../../limits";

interface Props {
  /** Titre de la carte (en-tête). */
  title: string;
  fieldLabel: string;
  placeholder: string;
  instructionPlaceholder: string;
  rows: number;
  value: string;
  /** Valeur enregistrée : « Rétablir l'original » apparaît quand `value` s'en écarte. */
  original: string;
  onChange: (value: string) => void;
  assist: { kind: AssistKind; context: AssistContext };
  /** Boutons d'action sous l'éditeur (génération). */
  children?: ReactNode;
}

/**
 * Carte d'un prompt (scène ou image de référence) : le champ d'`AssistField` (consigne facultative, un seul bouton,
 * annulation de la proposition) avec « Rétablir l'original ». Consigne et historique sont locaux : remonter le
 * composant (`key`) les remet à zéro.
 */
export default function PromptEditor({
  title, fieldLabel, placeholder, instructionPlaceholder, rows, value, original, onChange, assist, children,
}: Props) {
  const changed = value.trim() !== original.trim();
  return (
    <div className="prompt-editor-card">
      <div className="prompt-editor-header">
        <h4>{title}</h4>
        {changed && (
          <button type="button" className="btn btn-small btn-ghost" onClick={() => onChange(original)}>
            Rétablir l'original
          </button>
        )}
      </div>
      <AssistField
        label={fieldLabel}
        kind={assist.kind}
        value={value}
        onChange={onChange}
        context={assist.context}
        instructionPlaceholder={instructionPlaceholder}
      >
        {(f) => (
          <TextArea
            {...f}
            className="input input-tall"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={rows}
            maxLength={MAX_VISUAL_PROMPT}
          />
        )}
      </AssistField>
      {children}
    </div>
  );
}
