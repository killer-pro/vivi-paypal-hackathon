import type { PlanMessage } from "./api";
import { currentStep, hasResult, type Step } from "./steps";

/** Étapes du plan : l'idée, l'histoire (beats et éléments) puis les scènes. */
const PLAN_STEPS: Step["name"][] = ["idea", "story", "script"];

/** L'éditeur ne s'ouvre qu'une fois le plan (idée, histoire puis script) validé : avant, on passe par l'écran Plan. */
export function needsPlanScreen(steps: Pick<Step, "name" | "status">[]): boolean {
  return PLAN_STEPS.includes(currentStep(steps));
}

export type PlanPhase = "generating" | "failed" | "story" | "ready" | "empty";

/** Ce que montre l'écran Plan : génération en cours, échec (avec « Réessayer »), histoire à relire avant d'écrire les
 *  scènes, plan à relire, ou rien de généré. Un projet existant (histoire validée et vide) garde l'ancien parcours. */
export function planPhase(steps: Pick<Step, "name" | "status" | "result">[], sceneCount: number): PlanPhase {
  const planSteps = steps.filter((s) => PLAN_STEPS.includes(s.name));
  if (planSteps.some((s) => s.status === "running")) return "generating";
  if (planSteps.some((s) => s.status === "failed")) return "failed";
  const by = (name: Step["name"]) => planSteps.find((s) => s.name === name);
  if (by("script")?.status === "awaiting_validation" && sceneCount > 0) return "ready";
  const story = by("story");
  return story && hasResult(story) ? "story" : "empty";
}

export type PlanStepState = "done" | "running" | "failed" | "todo";

/** Ce que produit chaque étape du plan, dans l'ordre où elles s'enchaînent. */
const PLAN_STEP_TEXT: Record<string, { label: string; hint: string }> = {
  idea: { label: "Idée", hint: "L'angle et l'accroche de la vidéo" },
  story: { label: "Histoire", hint: "Les beats et les éléments suivis" },
  script: { label: "Scènes", hint: "La voix off et le visuel de chaque scène" },
};

/** Avancement de la génération du plan (écrans d'attente, d'échec et de départ) : une ligne par étape avec son état ;
 *  une étape à valider compte comme faite (son résultat existe), une étape périmée comme à refaire. */
export function planProgress<S extends Pick<Step, "name" | "status">>(
  steps: S[],
): { step: S; label: string; hint: string; state: PlanStepState }[] {
  const state = (status: Step["status"]): PlanStepState =>
    status === "running" ? "running"
    : status === "failed" ? "failed"
    : status === "approved" || status === "awaiting_validation" ? "done"
    : "todo";
  return PLAN_STEPS.flatMap((name) => {
    const step = steps.find((s) => s.name === name);
    return step ? [{ step, ...PLAN_STEP_TEXT[name], state: state(step.status) }] : [];
  });
}

/** « Écrire les scènes » valide l'histoire sauf si elle l'est déjà (modifiée après validation, ou relance échouée) :
 *  l'API refuse `approved` → `approved`. */
export const storyNeedsApproval = (steps: Pick<Step, "name" | "status">[]): boolean =>
  steps.find((s) => s.name === "story")?.status !== "approved";

/** Verrous de l'écran Plan. Les images de référence (`reference`) se génèrent pendant la relecture : elles ne gèlent
 *  ni la validation, ni l'enchaînement, ni les assistants (`locked` : action en cours ou autre étape qui tourne). L'API
 *  refuse seulement, tant qu'elles tournent, d'enregistrer le plan (`saveBlocked`, le job lit les scènes) et le chat
 *  (`running` : toute étape). */
export function planLocks(
  steps: Pick<Step, "name" | "status">[],
  busy: boolean,
): { locked: boolean; running: boolean; saveBlocked: string | null } {
  const running = steps.filter((s) => s.status === "running").map((s) => s.name);
  return {
    locked: busy || running.some((name) => name !== "reference"),
    running: running.length > 0,
    saveBlocked: running.includes("reference") ? "Les images du casting se génèrent : enregistrement possible à leur fin" : null,
  };
}

/** Raison pour laquelle on ne peut pas parler à l'IA maintenant (le serveur refuse aussi : 409), sinon `null`. */
export function chatBlockedReason({ dirty, running }: { dirty: boolean; running: boolean }): string | null {
  if (dirty) return "Enregistrez ou annulez vos modifications avant de parler à l'IA";
  if (running) return "Une génération est en cours : attendez sa fin ou arrêtez-la pour parler à l'IA";
  return null;
}

/** Le message dont le changement du plan peut être annulé (le serveur n'en désigne qu'un), `null` sinon. */
export function lastUndoable(messages: PlanMessage[]): PlanMessage | null {
  return messages.findLast((m) => m.can_undo) ?? null;
}
