import { useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api";
import { PASSWORD_RULE, tokenFromSearch, validPassword } from "../auth";
import { AuthCard, AuthForm, AuthMessage, PasswordField } from "../components/AuthCard";
import { t } from "../i18n";

const TITLE = t("Nouveau mot de passe");
const LOGIN = { to: "/login", label: t("Se connecter") };

export default function ResetPassword() {
  const token = tokenFromSearch(useLocation().search);
  const [password, setPassword] = useState("");

  if (!token)
    return (
      <AuthCard title={TITLE} links={[{ to: "/forgot", label: t("Demander un nouveau lien") }]}>
        <AuthMessage error>{t("Lien invalide ou expiré")}</AuthMessage>
      </AuthCard>
    );
  return (
    <AuthForm
      title={TITLE}
      submitLabel={t("Changer le mot de passe")}
      links={[LOGIN]}
      validate={() => (validPassword(password) ? null : PASSWORD_RULE)}
      onSubmit={async () => {
        await api("/auth/reset", { method: "POST", body: JSON.stringify({ token, password }) });
        // Les sessions ouvertes sont révoquées : il faut se reconnecter.
        return t("Mot de passe modifié. Connectez-vous avec le nouveau mot de passe.");
      }}
    >
      <PasswordField value={password} onChange={setPassword} create autoFocus />
    </AuthForm>
  );
}
