import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../api";
import { PASSWORD_MAX, PASSWORD_MIN } from "../auth";
import ClipWall from "./ClipWall";
import { Field } from "./ui";
import "../pages/Login.css";

/** Lien de bas de carte vers un autre écran de compte. */
export type AuthLink = { to: string; label: string };

/** Carte centrée des écrans hors session, sur le mur de clips de la page Découvrir : marque, titre, contenu, liens vers
 *  les autres écrans. `intro` : phrase d'accroche sous le titre. */
export function AuthCard({
  title,
  intro,
  links = [],
  children,
}: {
  title: string;
  intro?: ReactNode;
  links?: AuthLink[];
  children: ReactNode;
}) {
  return (
    <main className="center-screen auth-screen">
      <ClipWall />
      <div className="login-card">
        <Link className="login-head" to="/decouvrir">
          <span className="brand-mark" aria-hidden />
          <span className="login-brand">Vivi</span>
        </Link>
        <h1 className="login-title">{title}</h1>
        {intro && <p className="login-intro">{intro}</p>}
        {children}
        {links.length > 0 && (
          <nav className="login-links">
            {links.map((l) => (
              <Link key={l.to} to={l.to}>
                {l.label}
              </Link>
            ))}
          </nav>
        )}
      </div>
    </main>
  );
}

/** Message qui remplace un formulaire envoyé (ou un lien traité). */
export function AuthMessage({ children, error }: { children: ReactNode; error?: boolean }) {
  return (
    <p className={error ? "error login-message" : "login-message"} role={error ? "alert" : "status"}>
      {children}
    </p>
  );
}

/**
 * Formulaire d'écran de compte : gère l'envoi (bouton désactivé, erreur de l'API) puis affiche `done` à la place du
 * formulaire si l'envoi le renvoie. `validate` refuse l'envoi avec un message, sans appel.
 */
export function AuthForm({
  title,
  intro,
  submitLabel,
  links,
  validate,
  onSubmit,
  children,
}: {
  title: string;
  intro?: ReactNode;
  submitLabel: string;
  links?: AuthLink[];
  validate?: () => string | null;
  onSubmit: () => Promise<ReactNode | void>;
  children: ReactNode;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<ReactNode>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const invalid = validate?.() ?? null;
    setError(invalid);
    if (invalid) return;
    setBusy(true);
    try {
      setDone((await onSubmit()) ?? null);
    } catch (err) {
      setError(errorMessage(err));
    }
    setBusy(false);
  }

  return (
    <AuthCard title={title} intro={intro} links={links}>
      {done ? (
        <AuthMessage>{done}</AuthMessage>
      ) : (
        <form className="form" onSubmit={submit}>
          {children}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-primary login-submit" disabled={busy}>
            {submitLabel}
          </button>
        </form>
      )}
    </AuthCard>
  );
}

export function EmailField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Adresse e-mail">
      <input
        className="input"
        type="email"
        autoComplete="email"
        autoFocus
        required
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}

/** Mot de passe ; `create` : nouveau mot de passe (bornes rappelées sous le libellé). */
export function PasswordField({
  value,
  onChange,
  create,
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  create?: boolean;
  autoFocus?: boolean;
}) {
  return (
    <Field label={create ? `Mot de passe (${PASSWORD_MIN} caractères minimum)` : "Mot de passe"}>
      <input
        className="input"
        type="password"
        autoComplete={create ? "new-password" : "current-password"}
        autoFocus={autoFocus}
        required
        maxLength={PASSWORD_MAX}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}
