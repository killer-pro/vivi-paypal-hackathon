import { useId } from "react";
import { budgetState, costStepLabel } from "../costs";
import { usd } from "../format";

/**
 * Dépense de la vidéo, discrète : le total seul, le détail (par étape, plafond, ce qui est compté) au clic. Le plafond
 * ne s'affiche en clair qu'à l'approche de la limite, quand il devient utile.
 */
export default function CostSummary({
  spent,
  byStep,
  budget,
}: {
  spent: number;
  byStep: Record<string, number>;
  budget: number;
}) {
  const state = budgetState(spent, budget);
  const popId = useId();
  const rows = Object.entries(byStep).sort(([, a], [, b]) => b - a);
  return (
    // Détail au survol (ou au focus clavier, ou au toucher) : pas de clic nécessaire.
    <div className={`studio-cost is-${state}`}>
      <button type="button" className="cost-trigger" aria-describedby={popId}>
        <span className="muted">Dépensé</span> {usd.format(spent)}
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
          <p className="muted">Aucune dépense pour l'instant.</p>
        )}
        <p className="muted">{budget > 0 ? `Plafond par vidéo : ${usd.format(budget)}` : "Aucun plafond par vidéo"}</p>
      </div>
    </div>
  );
}
