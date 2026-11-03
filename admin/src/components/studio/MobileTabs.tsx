import type { ReactNode } from "react";
import { PreviewIcon, ScenesIcon, SettingsIcon } from "../icons";

export type Pane = "preview" | "scenes" | "step";

/** Barre d'onglets de l'éditeur sur petit écran : un seul des trois volets (aperçu, scènes, étape) est affiché à la fois. */
export default function MobileTabs({
  pane,
  onChange,
  sceneCount,
}: {
  pane: Pane;
  onChange: (pane: Pane) => void;
  sceneCount: number;
}) {
  const tabs: { id: Pane; label: string; icon: ReactNode }[] = [
    { id: "preview", label: "Aperçu", icon: <PreviewIcon /> },
    ...(sceneCount > 0 ? [{ id: "scenes" as const, label: `Scènes (${sceneCount})`, icon: <ScenesIcon /> }] : []),
    { id: "step", label: "Étape", icon: <SettingsIcon /> },
  ];
  return (
    <nav className="studio-tabs" aria-label="Volets de l'éditeur">
      {tabs.map((t) => (
        <button key={t.id} aria-current={t.id === pane ? "page" : undefined} onClick={() => onChange(t.id)}>
          {t.icon}
          {t.label}
        </button>
      ))}
    </nav>
  );
}
