import { useApi } from "../api";
import type { CreditsPage } from "../credits";
import { useEvents } from "../events";

/** Solde et dernier mouvements du compte connecté (`GET /api/credits`), rechargés à chaque événement d'étape : une
 *  génération réserve, règle ou rend des crédits. `limit` : mouvements demandés. */
export function useCredits(limit = 1) {
  const credits = useApi<CreditsPage>(`/credits?limit=${limit}`);
  useEvents(credits.reload);
  return credits;
}
