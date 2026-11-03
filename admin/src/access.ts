/** Ce que l'abonnement débloque pour le compte connecté (`GET /api/access`) : fonctions encore verrouillées et motif à
 *  afficher à leur place. Les profils vidéo portent leur propre verrou dans `GET /providers/models` (`locked`). */
export interface Access {
  subscribed: boolean;
  subscription_ends_at: string | null;
  locked: { profiles: string[]; reference: boolean; styles: string[] };
  reasons: { reference: string | null; style: string | null };
}

/** Motif qui empêche de générer ou d'importer une image de référence ; `undefined` si c'est permis (ou pas encore chargé). */
export function referenceBlocked(access: Access | undefined): string | undefined {
  return access?.locked.reference ? (access.reasons.reference ?? undefined) : undefined;
}
