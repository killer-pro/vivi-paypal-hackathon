import { useEffect, useState } from "react";

export type PanelId = "rail" | "panel";

interface PanelState {
  width: number;
  collapsed: boolean;
}

/** Largeur par défaut et bornes (px) des colonnes latérales de l'éditeur : scènes à gauche, panneau de l'étape à droite. */
export const PANEL_LIMITS: Record<PanelId, { fallback: number; min: number; max: number }> = {
  rail: { fallback: 252, min: 200, max: 480 },
  panel: { fallback: 380, min: 320, max: 720 },
};

const KEY = "studio-layout";
const clamp = (id: PanelId, width: number) => Math.min(PANEL_LIMITS[id].max, Math.max(PANEL_LIMITS[id].min, Math.round(width)));

function load(): Record<PanelId, PanelState> {
  const layout = { rail: { width: PANEL_LIMITS.rail.fallback, collapsed: false }, panel: { width: PANEL_LIMITS.panel.fallback, collapsed: false } };
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    for (const id of ["rail", "panel"] as const) {
      if (typeof saved[id]?.width === "number") layout[id].width = clamp(id, saved[id].width);
      layout[id].collapsed = saved[id]?.collapsed === true;
    }
  } catch {
    // stockage indisponible ou illisible : dispositions par défaut
  }
  return layout;
}

/** Disposition des colonnes latérales de l'éditeur (largeur réglable, repliage), mémorisée dans le navigateur. */
export function usePanelLayout() {
  const [layout, setLayout] = useState(load);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(layout));
    } catch {
      // mémorisation facultative
    }
  }, [layout]);

  const update = (id: PanelId, change: Partial<PanelState>) => setLayout((l) => ({ ...l, [id]: { ...l[id], ...change } }));
  return {
    layout,
    resize: (id: PanelId, width: number) => update(id, { width: clamp(id, width), collapsed: false }),
    toggle: (id: PanelId) => update(id, { collapsed: !layout[id].collapsed }),
    reset: (id: PanelId) => update(id, { width: PANEL_LIMITS[id].fallback, collapsed: false }),
  };
}
