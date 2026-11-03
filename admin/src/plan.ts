import type { Scene } from "./api";

/** Scène du brouillon du plan : `id` absent tant qu'elle n'est pas enregistrée, `key` stable pour React et l'assistant. */
export type DraftScene = Pick<Scene, "voice_text" | "visual_prompt" | "duration_s"> & { id?: number; key: string };

export const toDraft = (scenes: Scene[]): DraftScene[] =>
  scenes.map(({ id, voice_text, visual_prompt, duration_s }) => ({
    id,
    key: `scene-${id}`,
    voice_text,
    visual_prompt,
    duration_s,
  }));

export const planTotal = (list: DraftScene[]): number => list.reduce((sum, s) => sum + (s.duration_s || 0), 0);

/** Index de la première scène sans voix off ou sans prompt visuel (l'API refuse un texte vide), -1 si aucune. */
export const firstBlank = (list: DraftScene[]): number =>
  list.findIndex((s) => !s.voice_text.trim() || !s.visual_prompt.trim());

/** Échange l'élément `i` (scène ou beat) avec son voisin (`by` = ±1) ; la liste est rendue telle quelle aux bornes. */
export function moved<T>(list: T[], i: number, by: number): T[] {
  if (i + by < 0 || i + by >= list.length) return list;
  const next = [...list];
  [next[i], next[i + by]] = [next[i + by], next[i]];
  return next;
}

export const withoutAt = <T>(list: T[], i: number): T[] => list.filter((_, j) => j !== i);

export const newScene = (): DraftScene => ({
  key: crypto.randomUUID(),
  voice_text: "",
  visual_prompt: "",
  duration_s: 3,
});
