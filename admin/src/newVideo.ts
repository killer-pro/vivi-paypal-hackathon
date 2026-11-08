import type { StyleOption } from "./api";
import type { Template } from "./templates";
import { t } from "./i18n";

export const MIN_DURATION_S = 5;
export const MAX_DURATION_S = 180;
/** Durées proposées en un clic ; toute autre durée entre 5 et 180 s se saisit. */
export const DURATIONS = [15, 30, 45, 60];

const MAX_TITLE = 60;

/** Titre du projet tiré du sujet saisi : première ligne, coupée au mot sous 60 caractères. */
export function titleFromSubject(subject: string): string {
  const line = subject.trim().split("\n")[0].replace(/\s+/g, " ");
  if (!line) return t("Nouvelle vidéo");
  if (line.length <= MAX_TITLE) return line;
  const head = line.slice(0, MAX_TITLE);
  const space = head.lastIndexOf(" ");
  return `${space > 0 ? head.slice(0, space) : head.slice(0, MAX_TITLE - 1)}…`;
}

/** Durée saisie en secondes : un entier de 5 à 180, sinon `null`. */
export function parseDuration(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const seconds = Number(text);
  return seconds >= MIN_DURATION_S && seconds <= MAX_DURATION_S ? seconds : null;
}

export const canCreate = (subject: string, duration: string): boolean =>
  subject.trim() !== "" && parseDuration(duration) !== null;

/** Ce qu'un modèle remplit : l'idée, la durée (texte du champ) et la durée des scènes (`null` : libre). */
export const fromTemplate = (t: Template) => ({
  subject: t.subject,
  duration: String(t.duration_s),
  sceneLength: t.scene_length_s,
});

/** Choix unique du style : « Aucun » (valeur vide) puis les styles du serveur. Ceux que l'abonnement réserve (`locked`)
 *  restent visibles mais non choisissables, avec leur motif (`hint`). */
export const styleOptions = (
  styles: StyleOption[],
  locked: string[] = [],
  hint = "",
): { value: string; label: string; disabled?: boolean; hint?: string }[] => [
  { value: "", label: t("Aucun") },
  ...styles.map((s) => ({
    value: s.id,
    label: t(s.label),
    ...(locked.includes(s.id) ? { disabled: true, hint } : {}),
  })),
];

/** Durées proposées en un clic ; celles au-delà du forfait (`max`) restent visibles, désactivées, avec le motif. */
export const durationOptions = (max: number | undefined, hint = ""): { value: string; label: string; disabled?: boolean; hint?: string }[] =>
  DURATIONS.map((d) => ({ value: String(d), label: `${d} s`, ...(max !== undefined && d > max ? { disabled: true, hint } : {}) }));
