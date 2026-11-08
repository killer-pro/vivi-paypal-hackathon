import { useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../api";
import { ErrorState } from "../components/ui";
import { formatCredits, kindLabel, reasonLabel, type CreditEntry, type CreditsPage } from "../credits";
import { dateTime } from "../format";
import { useCredits } from "../hooks/useCredits";
import { STEP_LABELS, type StepName } from "../steps";
import "./Credits.css";
import { t } from "../i18n";

const STEP_EXTRA: Record<string, string> = { assist: t("Assistant IA"), plan_chat: t("Chat du plan") };
const stepLabel = (step: string) => STEP_LABELS[step as StepName] ?? STEP_EXTRA[step] ?? step;

/** Page de tête : un cran au-dessus du reste de l'écran, le solde ; dessous, le registre des mouvements. */
export default function Credits() {
  const { data, error, reload } = useCredits(50);
  // Pages plus anciennes demandées par « Afficher plus » ; `olderCursor` undefined tant qu'aucune n'est chargée.
  const [older, setOlder] = useState<CreditEntry[]>([]);
  const [olderCursor, setOlderCursor] = useState<number | null | undefined>();
  const [loading, setLoading] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <p className="muted">{t("Chargement…")}</p>;
  // La première page se recharge avec les événements : ses dernières lignes peuvent déjà figurer dans les pages chargées.
  const entries = [...new Map([...data.entries, ...older].map((e) => [e.id, e])).values()];
  const more = olderCursor === undefined ? data.next_before_id : olderCursor;
  async function loadMore() {
    setLoading(true);
    setMoreError(null);
    try {
      const page = await api<CreditsPage>(`/credits?limit=50&before_id=${more}`);
      setOlder((o) => [...o, ...page.entries]);
      setOlderCursor(page.next_before_id);
    } catch (err) {
      setMoreError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <header className="page-head">
        <h1>{t("Crédits")}</h1>
      </header>

      <section className="credit-summary" aria-label={t("Solde")}>
        <div className="credit-total">
          <span className="muted">{t("Solde")}</span>
          <strong>{data.unlimited ? t("Illimité") : formatCredits(data.balance.total)}</strong>
          {data.unlimited && <span className="muted">{t("Le compte administrateur n'est pas limité par ses crédits.")}</span>}
        </div>
        <div>
          <span className="muted">{t("Abonnement")}</span>
          <strong>{formatCredits(data.balance.subscription)}</strong>
          <span className="muted">{t("Consommés en premier")}</span>
        </div>
        <div>
          <span className="muted">{t("Rechargés")}</span>
          <strong>{formatCredits(data.balance.topup)}</strong>
          <span className="muted">{t("Offerts ou achetés")}</span>
        </div>
      </section>

      {!data.unlimited && (
        <p className="credit-plans">
          {t("Plus de crédits chaque mois, ou une recharge :")} <Link to="/plans">{t("Voir les forfaits")}</Link>
        </p>
      )}

      <h2 className="credit-history-title">{t("Historique")}</h2>
      {entries.length === 0 ? (
        <p className="muted">{t("Aucun mouvement : vos crédits d'inscription arrivent dès que votre adresse e-mail est confirmée.")}</p>
      ) : (
        <div className="table-wrap">
          <table className="table credit-table">
            <thead>
              <tr>
                <th>{t("Date")}</th>
                <th>{t("Mouvement")}</th>
                <th>{t("Projet")}</th>
                <th>{t("Étape")}</th>
                <th>{t("Motif")}</th>
                <th className="num">{t("Crédits")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="nowrap">{dateTime.format(new Date(e.created_at))}</td>
                  <td>{kindLabel(e.kind)}</td>
                  <td>{e.project_id ? <Link to={`/projects/${e.project_id}`}>Projet n° {e.project_id}</Link> : "—"}</td>
                  <td>{e.step ? stepLabel(e.step) : "—"}</td>
                  <td className="muted">{reasonLabel(e.reason)}</td>
                  <td className={`num ${e.amount > 0 ? "credit-in" : ""}`}>{e.amount > 0 ? `+${e.amount}` : e.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {moreError && (
        <p className="error" role="alert">
          {moreError}
        </p>
      )}
      {more !== null && (
        <button className="btn" onClick={loadMore} disabled={loading}>
          {t("Afficher plus")}
        </button>
      )}
    </>
  );
}
