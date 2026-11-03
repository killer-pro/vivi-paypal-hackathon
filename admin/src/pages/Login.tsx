import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { pendingIdea } from "../pendingIdea";
import { AuthForm, EmailField, PasswordField } from "../components/AuthCard";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();

  return (
    <AuthForm
      title="Se connecter"
      submitLabel="Se connecter"
      links={[
        { to: "/register", label: "Créer un compte" },
        { to: "/forgot", label: "Mot de passe oublié" },
      ]}
      onSubmit={async () => {
        await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
        navigate(pendingIdea() ? "/new" : "/"); // une idée venue de la page Découvrir attend sa vidéo
      }}
    >
      <EmailField value={email} onChange={setEmail} />
      <PasswordField value={password} onChange={setPassword} />
    </AuthForm>
  );
}
