import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, errorMessage } from "../api";
import { tokenFromSearch } from "../auth";
import { AuthCard, AuthMessage } from "../components/AuthCard";

type State = { ok: boolean; message: string } | null;

/** Confirme l'adresse au montage avec le jeton du lien reçu. La vérification révoque les sessions ouvertes : on
 *  renvoie vers la connexion. */
export default function Verify() {
  const token = tokenFromSearch(useLocation().search);
  const [state, setState] = useState<State>(token ? null : { ok: false, message: "Lien invalide ou expiré" });
  const sent = useRef(false); // jeton à usage unique : un seul appel, même si l'effet est rejoué (StrictMode)

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;
    api("/auth/verify", { method: "POST", body: JSON.stringify({ token }) }).then(
      () => setState({ ok: true, message: "Adresse e-mail confirmée. Connectez-vous pour continuer." }),
      (err) => setState({ ok: false, message: errorMessage(err) }),
    );
  }, [token]);

  return (
    <AuthCard title="Confirmation de l'adresse" links={state ? [{ to: "/login", label: "Se connecter" }] : []}>
      {state ? (
        <AuthMessage error={!state.ok}>{state.message}</AuthMessage>
      ) : (
        <p className="login-message muted">Vérification du lien…</p>
      )}
    </AuthCard>
  );
}
