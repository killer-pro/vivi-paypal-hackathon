import type { ReactNode } from "react";
import { planProgress, type PlanStepState } from "../../planChat";
import type { Step } from "../../steps";
import GenerationTiming from "../GenerationTiming";

/** Libellé (toujours affiché : l'état ne se lit jamais à la seule couleur) et classe de statut (`.st-*`) de chaque état. */
const STATES: Record<PlanStepState, { label: string; st: string }> = {
  done: { label: "Prête", st: "st-approved" },
  running: { label: "En cours", st: "st-running" },
  failed: { label: "Échec", st: "st-failed" },
  todo: { label: "À venir", st: "st-pending" },
};

interface Props {
  steps: Step[];
  title: string;
  lead: string;
  /** Bouton de l'écran : Arrêter, Réessayer ou Générer le plan. */
  children: ReactNode;
}

/** Écran Plan sans contenu à relire (génération en cours, échec, rien de généré) : les étapes du plan (idée, histoire,
 *  scènes) avec leur état, le temps écoulé de celle qui tourne et l'erreur de celle qui a échoué. */
export default function PlanProgress({ steps, title, lead, children }: Props) {
  return (
    <section className="plan-progress" aria-labelledby="plan-progress-title">
      <h2 id="plan-progress-title">{title}</h2>
      <p className="muted">{lead}</p>
      <ol className="plan-steps">
        {planProgress(steps).map(({ step, label, hint, state }, i) => (
          <li key={step.name} className={`plan-step ${STATES[state].st}`} aria-current={state === "running" ? "step" : undefined}>
            <span className="plan-step-mark" aria-hidden>
              {state === "running" ? <span className="spinner" /> : i + 1}
            </span>
            <div className="plan-step-text">
              <strong>{label}</strong>
              <span className="muted">{hint}</span>
              {state === "running" && <GenerationTiming step={step} />}
              {state === "failed" && step.error && <span className="error">{step.error}</span>}
            </div>
            <span className="status-badge">{STATES[state].label}</span>
          </li>
        ))}
      </ol>
      <div className="plan-progress-action">{children}</div>
    </section>
  );
}
