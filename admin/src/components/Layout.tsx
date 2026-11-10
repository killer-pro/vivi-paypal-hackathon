import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, errorMessage, useApi } from "../api";
import { visibleNav, type Me } from "../auth";
import { MeContext } from "../hooks/useMe";
import { CoinIcon, CostsIcon, LogoutIcon, MusicIcon, PlansIcon, ProjectsIcon, ScenesIcon, SettingsIcon } from "./icons";
import CreditBalance from "./CreditBalance";
import LangSwitch from "./LangSwitch";
import RouteErrorBoundary from "./RouteErrorBoundary";
import { ErrorState } from "./ui";
import "./Layout.css";
import { t } from "../i18n";

const NAV = [
  { to: "/", label: t("Projets"), icon: <ProjectsIcon />, end: true },
  { to: "/plans", label: t("Forfaits"), icon: <PlansIcon /> },
  { to: "/music", label: t("Musique"), icon: <MusicIcon />, adminOnly: true },
  { to: "/clients", label: t("Clients"), icon: <ScenesIcon />, adminOnly: true },
  { to: "/pricing", label: t("Tarifs"), icon: <CoinIcon />, adminOnly: true },
  { to: "/providers", label: t("Réglages"), icon: <SettingsIcon />, adminOnly: true },
  { to: "/costs", label: t("Coûts"), icon: <CostsIcon />, adminOnly: true },
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
      setLogoutError(t("Déconnexion impossible. {error}", { error: errorMessage(err) }));
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
            <LangSwitch />
            {logoutError && (
              <p className="error" role="alert">
                {logoutError}
              </p>
            )}
            <button className="nav-link" onClick={logout} title={t("Se déconnecter")}>
              <LogoutIcon />
              <span>{t("Sortir")}</span>
            </button>
          </div>
        </aside>
        <main className="main">
          <RouteErrorBoundary>
            <Outlet />
          </RouteErrorBoundary>
        </main>
      </div>
    </MeContext>
  );
}
