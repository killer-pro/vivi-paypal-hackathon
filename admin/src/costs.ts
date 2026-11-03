import { STEP_LABELS, type StepName } from "./steps";

/** Appels affichés par page ; « Afficher plus » en demande une page de plus (`limit` de `GET /api/costs`). */
export const CALLS_PAGE = 50;

export interface ProviderCall {
  id: number;
  project_id: number | null;
  step: string;
  provider: string;
  model: string;
  cost_usd: number;
  duration_ms: number;
  status: "ok" | "error";
  error: string | null;
  created_at: string;
}

/** Réponse de `GET /api/costs`. */
export interface Costs {
  total_usd: number;
  by_provider: Record<string, number>;
  by_project: Record<string, number>;
  calls: ProviderCall[];
  /** Appels correspondant aux filtres, au-delà de la page affichée. */
  calls_total: number;
}

export interface BreakdownRow {
  key: string;
  label: string;
  usd: number;
  /** Part du total (0 à 1). */
  share: number;
  /** Longueur de barre relative au plus gros poste (0 à 1). */
  ratio: number;
}

/** Répartition d'un total par clé, du plus gros au plus petit poste. */
export function breakdown(totals: Record<string, number>, labelOf: (key: string) => string): BreakdownRow[] {
  const entries = Object.entries(totals).sort(([, a], [, b]) => b - a);
  const total = entries.reduce((sum, [, usd]) => sum + usd, 0);
  const max = entries[0]?.[1] ?? 0;
  return entries.map(([key, usd]) => ({
    key,
    label: labelOf(key),
    usd,
    share: total > 0 ? usd / total : 0,
    ratio: max > 0 ? usd / max : 0,
  }));
}

const percent = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 0 });

/** Part du total en pourcent ; un poste non nul arrondi à 0 s'affiche « < 1 % ». */
export function formatShare(share: number): string {
  return share > 0 && share < 0.005 ? `< ${percent.format(0.01)}` : percent.format(share);
}

const OTHER_LABELS: Record<string, string> = { assist: "Assistant IA", plan_chat: "Chat du plan" };

/** Libellé d'un poste de dépense : une étape du flux, ou l'assistant IA (`assist`) et le chat du plan (`plan_chat`). */
export function costStepLabel(step: string): string {
  return OTHER_LABELS[step] ?? STEP_LABELS[step as StepName] ?? step;
}

/** Part du budget par vidéo à partir de laquelle la dépense passe d'une info discrète à un avertissement. */
export const BUDGET_WARNING = 0.8;

export type BudgetState = "none" | "ok" | "near" | "over";

/** Où en est la dépense d'une vidéo par rapport à son plafond (`budget` = 0 : sans limite). */
export function budgetState(spent: number, budget: number): BudgetState {
  if (budget <= 0) return "none";
  if (spent >= budget) return "over";
  return spent >= budget * BUDGET_WARNING ? "near" : "ok";
}
