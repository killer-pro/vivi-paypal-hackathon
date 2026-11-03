import { useState } from "react";
import { api } from "../api";
import { AuthForm, EmailField } from "../components/AuthCard";

/** Même message que le compte existe ou non. */
const SENT = "Si un compte existe pour cette adresse, un lien de réinitialisation vient d'être envoyé";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");

  return (
    <AuthForm
      title="Mot de passe oublié"
      submitLabel="Recevoir un lien"
      links={[{ to: "/login", label: "Retour à la connexion" }]}
      onSubmit={async () => {
        await api("/auth/forgot", { method: "POST", body: JSON.stringify({ email }) });
        return SENT;
      }}
    >
      <EmailField value={email} onChange={setEmail} />
    </AuthForm>
  );
}
