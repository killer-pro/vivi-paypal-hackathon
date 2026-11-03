import { useEffect, useState } from "react";
import { api } from "../api";
import type { PriceQuote } from "../credits";
import type { StepName } from "../steps";

/** Prix en crédits d'un lancement de `step` avec les options `body` (`POST …/steps/{étape}/price`), recalculé quand
 *  elles changent ou quand l'étape change d'état (`refreshKey` : un lancement modifie le solde). `body` null : pas de
 *  prix demandé. `null` tant qu'il est inconnu ou si l'API refuse le lancement (l'erreur s'affiche au lancement). */
export function usePrice(
  projectId: number,
  step: StepName,
  body: Record<string, unknown> | null,
  refreshKey: string,
): PriceQuote | null {
  // Le prix est rattaché à la demande qui l'a produit : celui d'une demande dépassée n'est jamais affiché.
  const [answer, setAnswer] = useState<{ request: string; quote: PriceQuote | null } | null>(null);
  const request = body === null ? null : `${projectId}/${step}/${refreshKey}/${JSON.stringify(body)}`;

  useEffect(() => {
    if (request === null) return;
    let stale = false;
    api<PriceQuote>(`/projects/${projectId}/steps/${step}/price`, { method: "POST", body: JSON.stringify(body) }).then(
      (quote) => !stale && setAnswer({ request, quote }),
      () => !stale && setAnswer({ request, quote: null }),
    );
    return () => {
      stale = true;
    };
    // `request` résume tous les autres paramètres
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  return answer && answer.request === request ? answer.quote : null;
}
