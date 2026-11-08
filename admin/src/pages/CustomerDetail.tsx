import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorMessage, useApi } from "../api";
import { Field, ErrorState } from "../components/ui";
import { adjustBody, planLabel, type Bucket, type CustomerDetail as Detail } from "../adminSaas";
import { formatCredits, kindLabel, reasonLabel, type CreditEntry } from "../credits";
import { dateTime } from "../format";
import "./Credits.css";
import "./Customers.css";
import { t } from "../i18n";

/** Un compte : offre, solde par lot, ajustement manuel (motif obligatoire, tracé dans le registre) et registre. */
export default function CustomerDetail() {
  const { id } = useParams();
  const { data, error, reload } = useApi<Detail>(`/admin/customers/${id}?limit=50`);
  const [older, setOlder] = useState<CreditEntry[]>([]);
  const [olderCursor, setOlderCursor] = useState<number | null | undefined>();
  const [amount, setAmount] = useState("");
  const [bucket, setBucket] = useState<Bucket>("topup");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState<{ error?: string; done?: boolean }>({});
  const [busy, setBusy] = useState(false);

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <p className="muted">{t("Chargement…")}</p>;
  const { customer } = data;
  const entries = [...new Map([...data.entries, ...older].map((e) => [e.id, e])).values()];
  const more = olderCursor === undefined ? data.next_before_id : olderCursor;

  async function loadMore() {
    const page = await api<Detail>(`/admin/customers/${id}?limit=50&before_id=${more}`);
    setOlder((o) => [...o, ...page.entries]);
    setOlderCursor(page.next_before_id);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = adjustBody(amount, bucket, reason);
    if (typeof body === "string") return setStatus({ error: body });
    setBusy(true);
    try {
      await api(`/admin/customers/${id}/credits`, { method: "POST", body: JSON.stringify(body) });
      setAmount("");
      setReason("");
      setOlder([]);
      setOlderCursor(undefined);
      setStatus({ done: true });
      reload();
    } catch (err) {
      setStatus({ error: errorMessage(err) });
    }
    setBusy(false);
  }

  return (
    <>
      <header className="page-head">
        <h1>{customer.email}</h1>
        <Link to="/clients" className="btn btn-small btn-ghost">
          {t("Tous les clients")}
        </Link>
      </header>
      <section className="credit-summary" aria-label={t("Compte")}>
        <div className="credit-total">
          <span className="muted">{planLabel(customer)}</span>
          <strong>{customer.role === "admin" ? t("Illimité") : formatCredits(customer.balance.total)}</strong>
          <span className="muted">{formatCredits(customer.spent)} consommés</span>
        </div>
        <div>
          <span className="muted">{t("Abonnement")}</span>
          <strong>{formatCredits(customer.balance.subscription)}</strong>
        </div>
        <div>
          <span className="muted">{t("Rechargés")}</span>
          <strong>{formatCredits(customer.balance.topup)}</strong>
        </div>
      </section>

      {customer.role !== "admin" && (
        <form className="adjust-form" onSubmit={submit}>
          <h2>{t("Ajuster les crédits")}</h2>
          <div className="adjust-fields">
            <Field label={t("Montant (négatif pour retirer)")}>
              <input className="input" inputMode="numeric" value={amount} placeholder="+50 ou -20" onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Field label={t("Lot")}>
              <select className="input" value={bucket} onChange={(e) => setBucket(e.target.value as Bucket)}>
                <option value="topup">{t("Rechargés")}</option>
                <option value="subscription">{t("Abonnement")}</option>
              </select>
            </Field>
            <Field label={t("Motif")}>
              <input className="input" value={reason} maxLength={300} placeholder={t("Ex. geste commercial")} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </div>
          {status.error && (
            <p className="error" role="alert">
              {status.error}
            </p>
          )}
          {status.done && <p className="muted">{t("Ajustement enregistré.")}</p>}
          <button className="btn btn-primary" disabled={busy}>
            {t("Enregistrer l'ajustement")}
          </button>
        </form>
      )}

      <h2 className="credit-history-title">{t("Registre")}</h2>
      {entries.length === 0 ? (
        <p className="muted">{t("Aucun mouvement.")}</p>
      ) : (
        <div className="table-wrap">
          <table className="table credit-table">
            <thead>
              <tr>
                <th>{t("Date")}</th>
                <th>{t("Mouvement")}</th>
                <th>{t("Lot")}</th>
                <th>{t("Motif")}</th>
                <th className="num">{t("Crédits")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="nowrap">{dateTime.format(new Date(e.created_at))}</td>
                  <td>{kindLabel(e.kind)}</td>
                  <td>{e.bucket === "topup" ? t("Rechargés") : t("Abonnement")}</td>
                  <td className="muted">{reasonLabel(e.reason)}</td>
                  <td className={`num ${e.amount > 0 ? "credit-in" : ""}`}>{e.amount > 0 ? `+${e.amount}` : e.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {more !== null && (
        <button className="btn" onClick={loadMore}>
          {t("Afficher plus")}
        </button>
      )}
    </>
  );
}
