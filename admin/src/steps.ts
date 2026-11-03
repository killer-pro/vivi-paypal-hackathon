import type { Asset, Scene } from "./api";

/** Noms et statuts alignés sur le backend (`app/state.py`). */
export const STEP_ORDER = ["idea", "story", "script", "reference", "clips", "voice", "music", "montage", "final"] as const;
export type StepName = (typeof STEP_ORDER)[number];

export const STEP_STATUSES = ["pending", "running", "awaiting_validation", "approved", "failed", "stale"] as const;
export type StepStatus = (typeof STEP_STATUSES)[number];

export interface Step {
  name: StepName;
  status: StepStatus;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  /** Étape par scène en échec qui a déjà produit des scènes : de quoi la reprendre sans tout régénérer. */
  resume?: { done: number; total: number } | null;
  /** Étape par scène dont le dernier lancement ne visait qu'une scène (en cours ou en échec) : « Relancer » ne refait
   *  que celle-là. */
  target_scene?: number | null;
  /** Étape par scène en cours pour toutes les scènes : scènes déjà produites sur le total. */
  progress?: { done: number; total: number } | null;
  /** Début de la génération en cours (ISO), sinon `null`. */
  running_since?: string | null;
}

/** Message d'une étape arrêtée par l'utilisateur (`STOPPED_BY_USER` côté API). */
export const STOPPED_BY_USER = "Arrêtée par l'utilisateur";

export const STEP_LABELS: Record<StepName, string> = {
  idea: "Idée",
  story: "Histoire et éléments",
  script: "Script et scènes",
  reference: "Image de référence",
  clips: "Clips",
  voice: "Voix off",
  music: "Musique",
  montage: "Montage",
  final: "Rendu final",
};

export const STATUS_LABELS: Record<StepStatus, string> = {
  pending: "À lancer",
  running: "En cours",
  awaiting_validation: "À valider",
  approved: "Validée",
  failed: "En échec",
  stale: "Périmée",
};

/** Étape optionnelle : en `pending`, elle n'empêche pas d'avancer. */
const OPTIONAL_STEP: StepName = "reference";

/** Première étape (dans l'ordre du flow) qui n'est pas validée ; `final` quand tout est validé. */
export function currentStep(steps: Pick<Step, "name" | "status">[]): StepName {
  const status = new Map(steps.map((s) => [s.name, s.status]));
  return (
    STEP_ORDER.find((name) => {
      const st = status.get(name) ?? "pending";
      return !(name === OPTIONAL_STEP && st === "pending") && st !== "approved";
    }) ?? "final"
  );
}

/** Étape -> étapes dont elle dépend directement (miroir de `REQUIRES`, `app/state.py`) : voix et musique ne dépendent
 *  que du script (écrit à partir de l'histoire), seul le montage rassemble clips, voix et musique. */
const REQUIRES: Record<StepName, StepName[]> = {
  idea: [],
  story: ["idea"],
  script: ["story"],
  reference: ["script"],
  clips: ["script", "reference"],
  voice: ["script"],
  music: ["script"],
  montage: ["clips", "voice", "music"],
  final: ["montage"],
};

/** Étapes dont `name` dépend, directement ou non. */
function upstream(name: StepName): StepName[] {
  const found = new Set<StepName>();
  const todo = [...REQUIRES[name]];
  for (let n = todo.pop(); n; n = todo.pop()) {
    if (!found.has(n)) {
      found.add(n);
      todo.push(...REQUIRES[n]);
    }
  }
  return STEP_ORDER.filter((n) => found.has(n));
}

/** Étapes construites à partir de `name` (miroir de `dependents`). */
export function dependents(name: StepName): StepName[] {
  return STEP_ORDER.filter((n) => upstream(n).includes(name));
}

/** Toutes les étapes obligatoires dont `name` dépend sont validées (miroir de `can_start` côté backend). */
export function previousApproved(steps: Pick<Step, "name" | "status">[], name: StepName): boolean {
  const required = upstream(name);
  return steps.every((s) => !required.includes(s.name) || s.name === OPTIONAL_STEP || s.status === "approved");
}

/** Étapes construites à partir de `name` en cours de génération : tant qu'elles tournent, l'API refuse (409) d'éditer
 *  ou de relancer `name` (le job en cours lit ses données). Miroir de `ensure_not_running(dependents(name))`. */
export function runningDownstream(steps: Pick<Step, "name" | "status">[], name: StepName): StepName[] {
  const after = dependents(name);
  return steps.filter((s) => after.includes(s.name) && s.status === "running").map((s) => s.name);
}

/** Étapes en aval qui ont déjà un résultat : relancer `name` les rend périmées. */
export function affectedDownstream(steps: Pick<Step, "name" | "result">[], name: StepName): StepName[] {
  const after = dependents(name);
  return steps.filter((s) => after.includes(s.name) && hasResult(s)).map((s) => s.name);
}

export interface StepActions {
  canRun: boolean;
  canApprove: boolean;
  showRetry: boolean;
  stale: boolean;
}

/** Actions proposées pour une étape. `stale → approved` (valider tel quel) est permis par le backend. */
export function availableActions(step: Pick<Step, "status">, previousApproved: boolean): StepActions {
  const { status } = step;
  const canRun = previousApproved && status !== "running";
  return {
    canRun,
    // Valider suppose l'amont validé : un résultat bâti sur une étape périmée ne doit pas être entériné.
    canApprove: previousApproved && (status === "awaiting_validation" || status === "stale"),
    showRetry: canRun && status === "failed",
    stale: status === "stale",
  };
}

/** L'étape a déjà produit un résultat (le backend crée les étapes avec `result = {}`). */
export function hasResult(step: Pick<Step, "result">): boolean {
  return Object.keys(step.result ?? {}).length > 0;
}

/** Libellé affiché d'un statut ; l'étape optionnelle est « Facultative » en attente, « Ignorée » si validée sans résultat. */
export function statusLabel(step: Pick<Step, "name" | "status" | "result">): string {
  if (step.name === OPTIONAL_STEP && step.status === "pending") return "Facultative";
  if (step.name === OPTIONAL_STEP && step.status === "approved" && !hasResult(step)) return "Ignorée";
  return STATUS_LABELS[step.status];
}

/** Reprise d'une étape par scène en échec : scènes restantes et phrase d'état (« 3 scènes sur 10 déjà générées »). */
export function resumeInfo({ done, total }: { done: number; total: number }): { remaining: number; text: string } {
  const plural = done > 1 ? "s" : "";
  return { remaining: Math.max(total - done, 0), text: `${done} scène${plural} sur ${total} déjà générée${plural}` };
}

/** Scènes sans aucun média du type (clip, voix) : `only_missing` ne génère que celles-là, sans toucher aux autres. */
export function missingScenes<S extends Pick<Scene, "id">>(
  scenes: S[],
  assets: Pick<Asset, "scene_id" | "kind">[],
  kind: Asset["kind"],
): S[] {
  const have = new Set(assets.filter((a) => a.kind === kind).map((a) => a.scene_id));
  return scenes.filter((s) => !have.has(s.id));
}
