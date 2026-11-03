/**
 * Calage voix et clip d'une scène, le même que le montage (`converge`, `backend/app/services/montage.py`) : l'aperçu
 * joue chaque scène à la durée et aux vitesses du rendu, sans couper la voix ni figer l'image.
 */
export const PAD_S = 0.3;
const MAX_TEMPO = 1.4;
const MIN_TEMPO = 0.85;
const MAX_STRETCH = 1.25;

export interface SceneTiming {
  /** Durée de la scène, marge comprise (secondes de timeline). */
  duration: number;
  /** Vitesse de lecture de la voix. */
  tempo: number;
  /** Vitesse de lecture du clip (1 / ralentissement). */
  rate: number;
}

const clamp = (x: number, low: number, high: number) => Math.min(Math.max(x, low), high);

/** Durée de la scène sans marge, vitesse de la voix et ralentissement du clip pour des durées d'origine données. */
export function converge(voiceS: number, clipS: number): { duration: number; tempo: number; stretch: number } {
  const middle = (voiceS + clipS) / 2;
  const lowest = Math.max(voiceS / MAX_TEMPO, clipS / MAX_STRETCH);
  const highest = Math.min(voiceS / MIN_TEMPO, clipS * MAX_STRETCH);
  const duration = lowest <= highest ? clamp(middle, lowest, highest) : clamp(middle, voiceS / MAX_TEMPO, voiceS / MIN_TEMPO);
  return { duration, tempo: voiceS / duration, stretch: clamp((duration + PAD_S) / clipS, 1 / MAX_STRETCH, MAX_STRETCH) };
}

/** Calage d'une scène ; tant qu'une durée manque (média pas encore mesuré, pas de voix), la durée prévue au script. */
export function sceneTiming(voiceS: number | undefined, clipS: number | undefined, plannedS: number): SceneTiming {
  if (!voiceS || !clipS) return { duration: plannedS, tempo: 1, rate: 1 };
  const { duration, tempo, stretch } = converge(voiceS, clipS);
  return { duration: duration + PAD_S, tempo, rate: 1 / stretch };
}
