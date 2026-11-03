import { useEffect } from "react";
import { useApi } from "../api";
import type { CreditsPage } from "../credits";
import { useEvents } from "../events";

const CHANGED = "credits:changed";

/** Prévient tous les `useCredits` montés (pastille de la barre latérale, page Crédits) que le solde a bougé hors d'une
 *  étape, par exemple après une recharge. */
export function notifyCreditsChanged(): void {
  window.dispatchEvent(new Event(CHANGED));
}

/** Solde et dernier mouvements du compte connecté (`GET /api/credits`), rechargés à chaque événement d'étape : une
 *  génération réserve, règle ou rend des crédits. `limit` : mouvements demandés. */
export function useCredits(limit = 1) {
  const credits = useApi<CreditsPage>(`/credits?limit=${limit}`);
  const { reload } = credits;
  useEvents(reload);
  useEffect(() => {
    window.addEventListener(CHANGED, reload);
    return () => window.removeEventListener(CHANGED, reload);
  }, [reload]);
  return credits;
}
