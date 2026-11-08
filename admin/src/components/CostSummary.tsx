import { useId } from "react";
import type { ProjectDetail } from "../api";
import { budgetState, costStepLabel } from "../costs";
import { formatCredits } from "../credits";
import { usd } from "../format";
import { t } from "../i18n";

/** Dépense de la vidéo : en crédits pour un client (jamais de dollars devant lui), en dollars avec le détail pour l'admin. */
export default function CostSummary({ project }: { project: ProjectDetail }) {
  if (project.cost_usd === null || project.cost_by_step === null || project.budget_usd === null) {
    return (
      <div className="studio-cost">
        <span className="muted">{t("Crédits utilisés :")}</span> {formatCredits(project.credits_spent ?? 0)}
      </div>
    );
  }
  return <DollarSummary spent={project.cost_usd} byStep={project.cost_by_step} budget={project.budget_usd} />;
}

/**
 * Dépense en dollars, discrète : le total seul, le détail (par étape, plafond, ce qui est compté) au survol. Le plafond
 * ne s'affiche en clair qu'à l'approche de la limite, quand il devient utile.
 */
function DollarSummary({ spent, byStep, budget }: { spent: number; byStep: Record<string, number>; budget: number }) {
  const state = budgetState(spent, budget);
  const popId = useId();
  const rows = Object.entries(byStep).sort(([, a], [, b]) => b - a);
  return (
    // Détail au survol (ou au focus clavier, ou au toucher) : pas de clic nécessaire.
    <div className={`studio-cost is-${state}`}>
      <button type="button" className="cost-trigger" aria-describedby={popId}>
        <span className="muted">{t("Dépensé")}</span> {usd.format(spent)}
        {(state === "near" || state === "over") && <span className="cost-limit"> sur {usd.format(budget)}</span>}
      </button>
      <div className="cost-pop" role="tooltip" id={popId}>
        {rows.length > 0 ? (
          <ul>
            {rows.map(([step, total]) => (
              <li key={step}>
                <span>{costStepLabel(step)}</span>
                <span>{usd.format(total)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">{t("Aucune dépense pour l'instant.")}</p>
        )}
        <p className="muted">{budget > 0 ? t("Plafond par vidéo : {amount}", { amount: usd.format(budget) }) : t("Aucun plafond par vidéo")}</p>
      </div>
    </div>
  );
}
