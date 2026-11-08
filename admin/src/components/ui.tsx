import { useEffect, useId, useRef, type ReactNode } from "react";
import { t } from "../i18n";

/** Libellé + contrôle de formulaire. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

/** Volet replié par défaut (« Avancé » : réglages techniques, providers, modèles, identifiants). */
export function Advanced({ label = t("Avancé"), children }: { label?: string; children: ReactNode }) {
  return (
    <details className="advanced">
      <summary>{label}</summary>
      <div className="advanced-body">{children}</div>
    </details>
  );
}

/** Modale sur `<dialog>` natif : focus piégé, fermeture par Échap ou clic sur le fond. Le focus initial va au
 *  premier élément focalisable (choix du navigateur). */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && ref.current.close()}
    >
      <div className="modal-head">
        <h2 id={titleId}>{title}</h2>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}

/** Échec de chargement : message et bouton pour relancer. */
export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="error-state" role="alert">
      <p className="error">{message}</p>
      <button className="btn" onClick={onRetry}>
        {t("Réessayer")}
      </button>
    </div>
  );
}

/** Boutons de fin de formulaire : « Annuler » puis l'envoi (`submit`). */
export function FormActions({
  submitLabel,
  onCancel,
  disabled,
  primary,
  hint,
}: {
  submitLabel: string;
  onCancel: () => void;
  disabled?: boolean;
  primary?: boolean;
  /** Pourquoi l'enregistrement attend, affiché devant les boutons. */
  hint?: string | null;
}) {
  return (
    <div className="form-actions">
      {hint && <span className="muted form-actions-hint">{hint}</span>}
      <button type="button" className="btn btn-ghost" onClick={onCancel}>
        {t("Annuler")}
      </button>
      <button className={primary ? "btn btn-primary" : "btn"} disabled={disabled}>
        {submitLabel}
      </button>
    </div>
  );
}

/** Demande de confirmation (modale native, pilotable au clavier et par l'automatisation, contrairement à `confirm()`). */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          onConfirm();
        }}
      >
        <p>{message}</p>
        <FormActions submitLabel={confirmLabel} onCancel={onCancel} primary />
      </form>
    </Modal>
  );
}
