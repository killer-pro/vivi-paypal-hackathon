import { useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api";
import { PASSWORD_RULE, tokenFromSearch, validPassword } from "../auth";
import { AuthCard, AuthForm, AuthMessage, PasswordField } from "../components/AuthCard";

const TITLE = "Nouveau mot de passe";
const LOGIN = { to: "/login", label: "Se connecter" };

export default function ResetPassword() {
  const token = tokenFromSearch(useLocation().search);
  const [password, setPassword] = useState("");

  if (!token)
    return (
      <AuthCard title={TITLE} links={[{ to: "/forgot", label: "Demander un nouveau lien" }]}>
        <AuthMessage error>Lien invalide ou expiré</AuthMessage>
      </AuthCard>
    );
  return (
    <AuthForm
      title={TITLE}
      submitLabel="Changer le mot de passe"
      links={[LOGIN]}
      validate={() => (validPassword(password) ? null : PASSWORD_RULE)}
      onSubmit={async () => {
        await api("/auth/reset", { method: "POST", body: JSON.stringify({ token, password }) });
        // Les sessions ouvertes sont révoquées : il faut se reconnecter.
        return "Mot de passe modifié. Connectez-vous avec le nouveau mot de passe.";
      }}
    >
      <PasswordField value={password} onChange={setPassword} create autoFocus />
    </AuthForm>
  );
}
