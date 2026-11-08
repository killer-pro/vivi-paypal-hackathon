import type { KeyboardEvent, PointerEvent } from "react";
import { PANEL_LIMITS, type PanelId } from "../../hooks/usePanelLayout";
import { ChevronLeftIcon, ChevronRightIcon } from "../icons";
import { t } from "../../i18n";

const KEY_STEP = 16;

/**
 * Bord d'une colonne latérale de l'éditeur : poignée à glisser (ou flèches du clavier) pour régler la largeur, double
 * clic pour la rétablir, bouton pour replier ou rouvrir la colonne. `id` dit de quelle colonne il s'agit : la poignée
 * des scènes est à droite de leur colonne, celle du panneau à gauche du sien.
 */
export default function PanelEdge({
  id,
  label,
  width,
  collapsed,
  onResize,
  onToggle,
  onReset,
}: {
  id: PanelId;
  /** Ce que la colonne contient : « les scènes », « le panneau de l'étape ». */
  label: string;
  width: number;
  collapsed: boolean;
  onResize: (width: number) => void;
  onToggle: () => void;
  onReset: () => void;
}) {
  const { min, max } = PANEL_LIMITS[id];
  const sign = id === "rail" ? 1 : -1; // glisser vers la droite agrandit les scènes, rétrécit le panneau

  function drag(e: PointerEvent<HTMLDivElement>) {
    if (collapsed) return;
    e.preventDefault();
    const start = { x: e.clientX, width };
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);
    const move = (ev: globalThis.PointerEvent) => onResize(start.width + sign * (ev.clientX - start.x));
    const stop = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", stop);
      target.removeEventListener("pointercancel", stop);
      document.body.classList.remove("is-resizing");
    };
    document.body.classList.add("is-resizing");
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", stop);
    target.addEventListener("pointercancel", stop);
  }

  function key(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    onResize(width + sign * (e.key === "ArrowRight" ? KEY_STEP : -KEY_STEP));
  }

  // Le chevron indique où va le bord : vers l'extérieur pour replier, vers l'intérieur pour rouvrir.
  const pointsLeft = (id === "rail") !== collapsed;
  return (
    <div className={`panel-edge edge-${id}${collapsed ? " is-collapsed" : ""}`}>
      {!collapsed && (
        <div
          className="edge-grip"
          role="separator"
          aria-orientation="vertical"
          aria-label={t("Largeur de {label}", { label })}
          aria-valuenow={width}
          aria-valuemin={min}
          aria-valuemax={max}
          tabIndex={0}
          onPointerDown={drag}
          onKeyDown={key}
          onDoubleClick={onReset}
        />
      )}
      <button
        className="edge-toggle"
        onClick={onToggle}
        aria-expanded={!collapsed}
        aria-label={`${collapsed ? "Afficher" : "Masquer"} ${label}`}
        title={`${collapsed ? "Afficher" : "Masquer"} ${label}`}
      >
        {pointsLeft ? <ChevronLeftIcon /> : <ChevronRightIcon />}
      </button>
    </div>
  );
}
