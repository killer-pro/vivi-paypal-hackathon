import { t } from "./i18n";

/** Avantages d'un forfait (`billing_config`) : limites et fonctions débloquées. */
export interface Perks {
  queue_max: number;
  references_max: number;
  profiles: string[];
  max_duration_s: number;
  parallel_clips: number;
  styles: boolean;
}

/** Forfait du compte connecté (`GET /api/access`), ses avantages et ce qu'il laisse verrouillé. Les profils vidéo portent
 *  leur propre verrou dans `GET /providers/models` (`locked`). */
export interface Access {
  subscribed: boolean;
  subscription_ends_at: string | null;
  tier: { id: string; name: string } | null;
  perks: Perks;
  locked: { profiles: string[]; styles: string[] };
  reasons: { style: string | null };
}

/** Motif qui empêche d'avoir `wanted` éléments de référence dans le projet ; `undefined` si c'est permis (ou pas encore
 *  chargé). Le serveur refuse de même, avec le forfait qui suffit. */
export function referenceLimit(access: Access | undefined, wanted: number): string | undefined {
  const max = access?.perks.references_max;
  return max !== undefined && wanted > max ? t("Limite de votre forfait : {n} images de référence", { n: max }) : undefined;
}

/** Éléments qui ont déjà une image de référence (`""` : image du projet, sans élément), comme le serveur les compte. */
export function referenceElementsOf(assets: { kind: string; meta: Record<string, unknown> }[]): Set<string> {
  return new Set(assets.filter((a) => a.kind === "reference").map((a) => (a.meta.ref as string | undefined) ?? ""));
}

/** Demandes en file par projet permises par le forfait ; une seule tant que l'accès n'est pas chargé. */
export function queueMax(access: Access | undefined): number {
  return access?.perks.queue_max ?? 1;
}
