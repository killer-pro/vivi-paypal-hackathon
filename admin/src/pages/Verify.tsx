import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api";
import { tokenFromSearch } from "../auth";
import { pendingIdea } from "../pendingIdea";
import { AuthCard, AuthMessage } from "../components/AuthCard";
import { t } from "../i18n";

/** Confirme l'adresse au montage avec le jeton du lien reçu. L'API connecte alors le titulaire du lien : on l'emmène dans
 *  l'app (ou vers l'idée qui attend sa vidéo). */
export default function Verify() {
  const token = tokenFromSearch(useLocation().search);
  const [error, setError] = useState<string | null>(token ? null : t("Lien invalide ou expiré"));
  const sent = useRef(false); // jeton à usage unique : un seul appel, même si l'effet est rejoué (StrictMode)
  const navigate = useNavigate();

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;
    api("/auth/verify", { method: "POST", body: JSON.stringify({ token }) }).then(
      () => navigate(pendingIdea() ? "/new" : "/", { replace: true }),
      (err) => setError(errorMessage(err)),
    );
  }, [token, navigate]);

  return (
    <AuthCard title={t("Confirmation de l'adresse")} links={error ? [{ to: "/login", label: t("Se connecter") }] : []}>
      {error ? (
        <AuthMessage error>{error}</AuthMessage>
      ) : (
        <p className="login-message muted">{t("Vérification du lien…")}</p>
      )}
    </AuthCard>
  );
}
