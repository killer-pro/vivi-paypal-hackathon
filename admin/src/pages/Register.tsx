import { useState } from "react";
import { api } from "../api";
import { PASSWORD_RULE, validPassword } from "../auth";
import { pendingIdea } from "../pendingIdea";
import { AuthForm, EmailField, PasswordField } from "../components/AuthCard";
import { t } from "../i18n";

/** Même message que l'adresse soit libre ou déjà prise : la réponse ne révèle pas les comptes existants. */
const SENT = t("Si cette adresse est valide, un lien de confirmation vient d'être envoyé");

export default function Register() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const idea = pendingIdea();

  return (
    <AuthForm
      title={t("Créer un compte")}
      intro={idea ? <>{t("Votre idée vous attend :")} <q>{idea.length > 90 ? `${idea.slice(0, 90)}…` : idea}</q> {t("Créez votre compte pour la transformer en vidéo.")}</> : undefined}
      submitLabel={t("Créer le compte")}
      links={[{ to: "/login", label: t("J'ai déjà un compte") }]}
      validate={() => (validPassword(password) ? null : PASSWORD_RULE)}
      onSubmit={async () => {
        await api("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) });
        return SENT;
      }}
    >
      <EmailField value={email} onChange={setEmail} />
      <PasswordField value={password} onChange={setPassword} create />
    </AuthForm>
  );
}
