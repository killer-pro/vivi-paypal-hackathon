import type { Perks } from "./access";
import { t, tn } from "./i18n";

/** Noms des profils de génération, dans l'ordre de `providers/profiles.py`. */
const PROFILE_NAMES: [string, string][] = [
  ["fast", t("Rapide")],
  ["balanced", t("Équilibré")],
  ["precision", t("Précision")],
  ["max", t("Maximum")],
];

/** Lignes cochées d'une carte de forfait : chaque avantage en clair (les styles seulement s'ils sont compris). */
export function perkLines(perks: Perks): string[] {
  const profiles = PROFILE_NAMES.filter(([id]) => perks.profiles.includes(id)).map(([, name]) => name);
  return [
    tn(perks.queue_max, "{n} demande en file par projet", "{n} demandes en file par projet"),
    tn(perks.references_max, "{n} image de référence par projet", "{n} images de référence par projet"),
    t("Profils {list}", { list: profiles.join(", ") }),
    t("Vidéos jusqu'à {n} s", { n: perks.max_duration_s }),
    tn(perks.parallel_clips, "{n} clip généré à la fois", "{n} clips générés en même temps"),
    ...(perks.styles ? [t("Styles visuels")] : []),
  ];
}

/** État d'un forfait pour le compte : celui qu'il a, ou un autre qu'il peut prendre. */
export function tierState(tier: { id: string }, current: string | null): "current" | "available" {
  return tier.id === current ? "current" : "available";
}
