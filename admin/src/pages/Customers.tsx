import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import { ErrorState } from "../components/ui";
import { planLabel, type CustomerList } from "../adminSaas";
import { formatCredits } from "../credits";
import { dateTime } from "../format";
import "./Customers.css";
import { t } from "../i18n";

const PAGE = 50;

/** Comptes clients : offre, solde et crédits consommés ; la recherche filtre sur l'adresse e-mail. */
export default function Customers() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const { data, error, reload } = useApi<CustomerList>(
    `/admin/customers?limit=${PAGE}&offset=${page * PAGE}&q=${encodeURIComponent(query.trim())}`,
  );

  return (
    <>
      <header className="page-head">
        <h1>{t("Clients")}</h1>
        <input
          className="input customers-search"
          type="search"
          placeholder={t("Rechercher une adresse e-mail")}
          aria-label={t("Rechercher un client")}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
      </header>
      {error && <ErrorState message={error} onRetry={reload} />}
      {!error && !data && <p className="muted">{t("Chargement…")}</p>}
      {data && data.customers.length === 0 && <p className="muted">{t("Aucun compte ne correspond.")}</p>}
      {data && data.customers.length > 0 && (
        <div className="table-wrap">
          <table className="table customers-table">
            <thead>
              <tr>
                <th>{t("Compte")}</th>
                <th>{t("Offre")}</th>
                <th className="num">{t("Solde")}</th>
                <th className="num">{t("Consommés")}</th>
                <th>{t("Inscrit le")}</th>
              </tr>
            </thead>
            <tbody>
              {data.customers.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/clients/${c.id}`}>{c.email}</Link>
                    {!c.verified && <span className="muted">{t(" · adresse non confirmée")}</span>}
                  </td>
                  <td>{planLabel(c)}</td>
                  <td className="num">{c.role === "admin" ? t("Illimité") : formatCredits(c.balance.total)}</td>
                  <td className="num">{formatCredits(c.spent)}</td>
                  <td className="nowrap muted">{dateTime.format(new Date(c.created_at))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > PAGE && (
        <div className="customers-pager">
          <button className="btn btn-small" disabled={page === 0} onClick={() => setPage(page - 1)}>
            {t("Précédents")}
          </button>
          <span className="muted">
            {page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)} sur {data.total}
          </span>
          <button className="btn btn-small" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>
            {t("Suivants")}
          </button>
        </div>
      )}
    </>
  );
}
