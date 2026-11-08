import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  ASSIST_LABELS,
  assistBlocked,
  assistBody,
  canUndo,
  MAX_INSTRUCTION,
  replyIsStale,
  requestAssist,
  type AssistContext,
  type AssistKind,
  type AssistMode,
} from "../assist";
import { errorMessage } from "../api";
import { TuneIcon, WandIcon } from "./icons";
import TextArea from "./TextArea";
import { t } from "../i18n";

interface AssistFieldProps {
  label: string;
  kind: AssistKind;
  value: string;
  /** Écrit dans le brouillon du champ (jamais enregistré directement). Doit cibler ce champ seul (mise à jour
   *  fonctionnelle du brouillon) : la réponse arrive après d'éventuelles autres modifications du formulaire. */
  onChange: (next: string) => void;
  context?: AssistContext;
  /** Précision des libellés accessibles quand le même champ se répète (ex. « scène 2 »). */
  scope?: string;
  /** Étape verrouillée (génération en cours, en aval comprise, ou enregistrement) : assistant inactif. */
  locked?: boolean;
  /** Brouillon non enregistré ; à `false` (enregistré, annulé ou rechargé), l'annulation de la proposition disparaît. */
  unsaved?: boolean;
  /** Texte d'exemple du champ de consigne (défaut : consignes génériques). */
  instructionPlaceholder?: string;
  /** Le contrôle du champ : `id` le relie au libellé, `readOnly` pendant la demande de ce champ. */
  children: (field: { id: string; readOnly: boolean }) => ReactNode;
}

/**
 * Champ texte avec assistant IA : le champ, une consigne facultative et un seul bouton (« Générer » quand le champ est
 * vide, « Améliorer » sinon). La proposition remplace le texte du brouillon ; « Annuler la proposition » rétablit le texte précédent tant que le champ la contient. Une
 * réponse arrivée alors que le champ a changé depuis la demande est ignorée.
 */
export default function AssistField({
  label,
  kind,
  value,
  onChange,
  context,
  scope,
  locked = false,
  unsaved,
  instructionPlaceholder = t("Consigne pour l'IA (facultative) : plus court, plus punchy, ton humoristique…"),
  children,
}: AssistFieldProps) {
  const id = useId();
  const [loading, setLoading] = useState<AssistMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [instructing, setInstructing] = useState(false);
  const [applied, setApplied] = useState<{ previous: string; result: string } | null>(null);
  // Valeur et callback les plus récents, lus à l'arrivée de la réponse (et non ceux du clic).
  const latest = useRef({ value, onChange });
  useEffect(() => {
    latest.current = { value, onChange };
  });
  // Brouillon enregistré, annulé ou rechargé : la proposition n'est plus annulable (ajustement pendant le rendu).
  if (unsaved === false && applied !== null) setApplied(null);
  const name = scope ? `${ASSIST_LABELS[kind]}, ${scope}` : ASSIST_LABELS[kind];

  async function ask(requested: AssistMode) {
    if (assistBlocked(requested, value, locked, loading !== null)) return;
    const sent = value;
    setLoading(requested);
    setError(null);
    try {
      const result = await requestAssist(assistBody(kind, requested, sent, instruction, context));
      if (replyIsStale(sent, latest.current.value)) {
        setError(t("Le champ a changé pendant la demande : proposition ignorée."));
        return;
      }
      setApplied({ previous: canUndo(sent, applied) ? applied!.previous : sent, result });
      latest.current.onChange(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(null);
    }
  }

  function undo() {
    if (!applied) return;
    latest.current.onChange(applied.previous);
    setApplied(null);
  }

  const mode: AssistMode = value.trim() ? "rewrite" : "generate";
  const blocked = assistBlocked(mode, value, locked, loading !== null);
  const verb = mode === "rewrite" ? t("Améliorer") : t("Générer");

  return (
    <div className={`field assist-field${loading ? " is-assisting" : ""}`} aria-busy={loading !== null}>
      <div className="assist-head">
        <label htmlFor={id}>{label}</label>
        <div className="assist-actions">
          <button
            type="button"
            className="btn btn-small btn-ghost btn-icon"
            onClick={() => setInstructing((v) => !v)}
            aria-expanded={instructing}
            aria-label={t("Consigne pour l'IA : {name}", { name })}
            title={t("Ajouter une consigne")}
          >
            <TuneIcon />
          </button>
          {/* `aria-disabled` plutôt que `disabled` : le bouton reste focalisable et sa raison (infobulle) lisible. */}
          <button
            type="button"
            className="btn btn-small btn-ghost"
            onClick={() => ask(mode)}
            aria-disabled={blocked !== null}
            title={blocked && loading === null ? blocked : undefined}
            aria-label={t("{verb} avec l'IA : {name}", { verb, name })}
          >
            {!loading && <WandIcon />}
            {loading ? (mode === "rewrite" ? t("Amélioration…") : t("Génération…")) : verb}
          </button>
        </div>
      </div>
      {children({ id, readOnly: loading !== null })}
      {instructing && (
        <TextArea
          id={`${id}-instruction`}
          className="input assist-instruction"
          autoFocus
          rows={2}
          aria-label={t("Consigne pour l'IA : {name} (Ctrl+Entrée pour lancer)", { name })}
          placeholder={instructionPlaceholder}
          maxLength={MAX_INSTRUCTION}
          value={instruction}
          disabled={loading !== null}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            // Entrée va à la ligne (consigne longue) ; Ctrl ou Cmd + Entrée lance la demande.
            if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || e.nativeEvent.isComposing) return;
            e.preventDefault(); // pas d'envoi du formulaire parent
            ask(mode);
          }}
        />
      )}
      {error && (
        <p className="error assist-note" role="alert">
          {error}
        </p>
      )}
      {canUndo(value, applied) && (
        <p className="assist-note" role="status">
          <span className="muted">{t("Proposition de l'IA, pas encore enregistrée.")}</span>
          <button type="button" className="assist-btn" onClick={undo} aria-label={t("Annuler la proposition : {name}", { name })}>
            {t("Annuler la proposition")}
          </button>
        </p>
      )}
    </div>
  );
}
