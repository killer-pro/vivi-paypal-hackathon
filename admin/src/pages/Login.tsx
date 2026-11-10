import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, errorMessage } from "../api";
import { pendingIdea } from "../pendingIdea";
import { AuthForm, EmailField, PasswordField } from "../components/AuthCard";
import { t } from "../i18n";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // Mot de passe juste mais adresse non confirmée (403) : on propose de renvoyer le lien de confirmation.
  const [unverified, setUnverified] = useState(false);
  const navigate = useNavigate();

  return (
    <AuthForm
      title={t("Se connecter")}
      submitLabel={t("Se connecter")}
      links={[
        { to: "/register", label: t("Créer un compte") },
        { to: "/forgot", label: t("Mot de passe oublié") },
      ]}
      onSubmit={async () => {
        try {
          await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
        } catch (err) {
          setUnverified(err instanceof ApiError && err.status === 403);
          throw err;
        }
        navigate(pendingIdea() ? "/new" : "/"); // une idée venue de la page Découvrir attend sa vidéo
      }}
    >
      <EmailField value={email} onChange={setEmail} />
      <PasswordField value={password} onChange={setPassword} />
      {unverified && <ResendLink email={email} password={password} />}
    </AuthForm>
  );
}

/** Nouveau lien de confirmation : l'API exige le mot de passe, seul le titulaire du compte peut le redemander. */
function ResendLink({ email, password }: { email: string; password: string }) {
  const [state, setState] = useState<{ busy?: boolean; message?: string; error?: boolean }>({});

  async function resend() {
    setState({ busy: true });
    try {
      await api("/auth/resend", { method: "POST", body: JSON.stringify({ email, password }) });
      setState({ message: t("Lien envoyé : consultez votre boîte de réception.") });
    } catch (err) {
      setState({ message: errorMessage(err), error: true });
    }
  }

  return (
    <div className="login-resend">
      <button type="button" className="btn btn-small btn-ghost" onClick={resend} disabled={state.busy}>
        {t("Renvoyer le lien")}
      </button>
      {state.message && (
        <p className={state.error ? "error" : "muted"} role={state.error ? "alert" : "status"}>
          {state.message}
        </p>
      )}
    </div>
  );
}
