import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, errorMessage, useApi } from "../api";
import { visibleNav, type Me } from "../auth";
import { MeContext } from "../hooks/useMe";
import { CoinIcon, CostsIcon, LogoutIcon, MusicIcon, ProjectsIcon, ScenesIcon, SettingsIcon } from "./icons";
import CreditBalance from "./CreditBalance";
import RouteErrorBoundary from "./RouteErrorBoundary";
import { ErrorState } from "./ui";
import "./Layout.css";

const NAV = [
  { to: "/", label: "Projets", icon: <ProjectsIcon />, end: true },
  { to: "/music", label: "Musique", icon: <MusicIcon />, adminOnly: true },
  { to: "/clients", label: "Clients", icon: <ScenesIcon />, adminOnly: true },
  { to: "/pricing", label: "Tarifs", icon: <CoinIcon />, adminOnly: true },
  { to: "/providers", label: "Réglages", icon: <SettingsIcon />, adminOnly: true },
  { to: "/costs", label: "Coûts", icon: <CostsIcon /> },
];

/** Coque des écrans connectés : vérifie la session (`GET /auth/me`), fournit le compte (`useMe`) puis affiche la barre
 *  latérale, filtrée selon le rôle. L'éditeur (`/projects/:id`) occupe tout l'écran : il a son propre rail d'outils et
 *  son bouton de retour aux projets. */
export default function Layout() {
  const session = useApi<Me>("/auth/me");
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const navigate = useNavigate();
  const inEditor = useLocation().pathname.startsWith("/projects/");

  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      navigate("/login");
    } catch (err) {
      setLogoutError(`Déconnexion impossible. ${errorMessage(err)}`);
    }
  }

  if (session.error)
    return (
      <main className="center-screen">
        <ErrorState message={session.error} onRetry={session.reload} />
      </main>
    );
  if (!session.data) return null; // vérification en cours, ou 401 : redirection vers /decouvrir
  const me = session.data;
  if (inEditor)
    return (
      <MeContext value={me}>
        <RouteErrorBoundary>
          <Outlet />
        </RouteErrorBoundary>
      </MeContext>
    );
  return (
    <MeContext value={me}>
      <div className="shell">
        <aside className="sidebar">
          <span className="sidebar-brand" title="Vivi">
            <span className="brand-mark" aria-hidden />
            Vivi
          </span>
          <nav className="nav">
            {visibleNav(NAV, me.role).map(({ to, label, icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className="nav-link" // NavLink ajoute `active` sur la page courante
              >
                {icon}
                <span>{label}</span>
              </NavLink>
            ))}
            <CreditBalance />
          </nav>
          <div className="logout">
            {logoutError && (
              <p className="error" role="alert">
                {logoutError}
              </p>
            )}
            <button className="nav-link" onClick={logout} title="Se déconnecter">
              <LogoutIcon />
              <span>Sortir</span>
            </button>
          </div>
        </aside>
        <main className="main">
          {!me.email_verified && <VerifyBanner />}
          <RouteErrorBoundary>
            <Outlet />
          </RouteErrorBoundary>
        </main>
      </div>
    </MeContext>
  );
}

/** Rappel discret tant que l'adresse n'est pas confirmée, avec renvoi du lien. */
function VerifyBanner() {
  const [state, setState] = useState<{ busy?: boolean; message?: string; error?: boolean }>({});

  async function resend() {
    setState({ busy: true });
    try {
      await api("/auth/resend", { method: "POST" });
      setState({ message: "Lien envoyé : consultez votre boîte de réception." });
    } catch (err) {
      setState({ message: errorMessage(err), error: true });
    }
  }

  return (
    <div className="verify-banner" role="status">
      <span>Confirmez votre adresse e-mail</span>
      {state.message && <span className={state.error ? "error" : "muted"}>{state.message}</span>}
      <button className="btn btn-small btn-ghost" onClick={resend} disabled={state.busy}>
        Renvoyer le lien
      </button>
    </div>
  );
}
