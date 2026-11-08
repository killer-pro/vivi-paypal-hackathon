import { t } from "./i18n";

/** Modèles de messages que le serveur écrit en français (motif d'indisponibilité d'un modèle, accès réservé à
 *  un forfait) ; `{0}`, `{1}` reprennent ce qui varie. */
const SERVER_TEXTS: [RegExp, string][] = [
  [/^Clé API (.+) manquante, à saisir dans Réglages → (.+)$/, "Clé API {0} manquante, à saisir dans Réglages → {1}"],
  [/^Modèle manquant : (.+)$/, "Modèle manquant : {0}"],
  [/^Réservé au forfait (.+?) : (.+)$/, "Réservé au forfait {0} : {1}"],
  [/^Indisponible : (.+)$/, "Indisponible : {0}"],
  [/^(\d+) \$ par mois$/, "{0} $ par mois"],
  [/^Limite de votre forfait : (.+) \(forfait (.+) : (.+)\)$/, "Limite de votre forfait : {0} (forfait {1} : {2})"],
  [/^Limite de votre forfait : (.+)$/, "Limite de votre forfait : {0}"],
];

/** Message du serveur dans la langue de l'interface ; ce qui n'est pas un modèle connu reste tel quel. */
export function serverText(text: string): string {
  for (const [pattern, key] of SERVER_TEXTS) {
    const found = text.match(pattern);
    if (found) {
      const [, ...parts] = found;
      return t(key, Object.fromEntries(parts.map((part, i) => [i, t(part)])));
    }
  }
  return t(text);
}
