import { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { useApi, type Page, type Project } from "../api";
import { ErrorState, Field } from "../components/ui";
import { breakdown, CALLS_PAGE, formatShare, type BreakdownRow, type Costs as CostsData } from "../costs";
import { useEvents } from "../events";
import { dateTime, plainTitle, usd } from "../format";
import { assistStepLabel } from "../assist";
import { STEP_LABELS, type StepName } from "../steps";
import "./Costs.css";
import { locale, t } from "../i18n";

const seconds = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });

type Filter = "project_id" | "provider";

export default function Costs() {
  const [params, setParams] = useSearchParams();
  const projectId = params.get("project_id") ?? "";
  const provider = params.get("provider") ?? "";
  // « Afficher plus » demande une page d'appels de plus ; la liste est rechargée depuis le début.
  const [limit, setLimit] = useState(CALLS_PAGE);
  const query = new URLSearchParams(params);
  query.set("limit", String(limit));
  const { data, error, status, reload } = useApi<CostsData>(`/costs?${query}`);
  const projects = useApi<Page<Project>>("/projects?limit=100&sort=title").data?.items; // noms des projets (100 au plus)
  const providers = useKnownProviders(data, provider);
  useEvents(reload); // une étape terminée ajoute des appels

  const titleOf = (id: string) => plainTitle(projects?.find((p) => String(p.id) === id)?.title ?? "") || `Projet n° ${id}`;
  const setFilter = (key: Filter, value: string) => {
    setLimit(CALLS_PAGE);
    setParams((p) => {
      if (value) p.set(key, value);
      else p.delete(key);
      return p;
    });
  };
  const failures = data?.calls.filter((c) => c.status === "error").length ?? 0;

  // Filtre sur un projet supprimé ou d'un autre compte (lien ancien) : 404, on revient à tous les projets.
  if (status === 404 && projectId) {
    const rest = new URLSearchParams(params);
    rest.delete("project_id");
    return <Navigate to={`/costs?${rest}`} replace />;
  }

  return (
    <>
      <header className="page-head">
        <h1>{t("Coûts")}</h1>
      </header>

      <div className="cost-filters">
        <Field label={t("Projet")}>
          <select className="input" value={projectId} onChange={(e) => setFilter("project_id", e.target.value)}>
            <option value="">{t("Tous les projets")}</option>
            {projects?.map((p) => (
              <option key={p.id} value={p.id}>
                {plainTitle(p.title)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Provider">
          <select className="input" value={provider} onChange={(e) => setFilter("provider", e.target.value)}>
            <option value="">{t("Tous les providers")}</option>
            {providers.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        {(projectId || provider) && (
          <button
            className="btn btn-ghost"
            onClick={() => {
              setLimit(CALLS_PAGE);
              setParams({});
            }}
          >
            {t("Effacer les filtres")}
          </button>
        )}
      </div>

      {error && <ErrorState message={error} onRetry={reload} />}
      {!error && !data && <p className="muted">{t("Chargement…")}</p>}

      {!error && data && (
        <>
          <section className="cost-summary" aria-label={t("Synthèse")}>
            <div className="cost-total">
              <span className="muted">{projectId || provider ? t("Dépensé (filtré)") : t("Dépensé")}</span>
              <strong>{usd.format(data.total_usd)}</strong>
              <span className="muted">
                {data.calls.length < data.calls_total
                  ? t("{n} derniers appels affichés sur {total}", { n: data.calls.length, total: data.calls_total })
                  : t("{n} appels", { n: data.calls_total })}
                {failures > 0 && t(", dont {n} en échec", { n: failures })}
              </span>
            </div>
            <Breakdown
              title={t("Par provider")}
              rows={breakdown(data.by_provider, (k) => k)}
              active={provider}
              onSelect={(k) => setFilter("provider", k)}
            />
            <Breakdown
              title={t("Par projet")}
              rows={breakdown(data.by_project, titleOf)}
              active={projectId}
              onSelect={(k) => setFilter("project_id", k)}
            />
          </section>

          <h2 className="calls-title">{t("Appels")}</h2>
          {data.calls.length === 0 ? (
            <p className="muted">
              {projectId || provider ? t("Aucun appel facturé pour ces filtres.") : t("Aucun appel facturé : lancez une génération depuis un projet.")}
            </p>
          ) : (
            <div className="table-wrap">
              <table className="table calls-table">
                <thead>
                  <tr>
                    <th>{t("Date")}</th>
                    <th>{t("Projet")}</th>
                    <th>{t("Étape")}</th>
                    <th>{t("Provider et modèle")}</th>
                    <th className="num">{t("Durée")}</th>
                    <th className="num">{t("Coût")}</th>
                    <th>{t("Statut")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.calls.map((c) => (
                    <tr key={c.id}>
                      <td className="nowrap">{dateTime.format(new Date(c.created_at))}</td>
                      <td>
                        {c.project_id === null ? (
                          <span className="muted">{t("Aucun")}</span>
                        ) : (
                          <Link to={`/projects/${c.project_id}`}>{titleOf(String(c.project_id))}</Link>
                        )}
                      </td>
                      <td className="nowrap">{STEP_LABELS[c.step as StepName] ?? assistStepLabel(c.step) ?? c.step}</td>
                      <td>
                        {c.provider}
                        <div className="muted call-model">{c.model}</div>
                      </td>
                      <td className="num">{seconds.format(c.duration_ms / 1000)} s</td>
                      <td className="num">{usd.format(c.cost_usd)}</td>
                      <td>
                        <span className={`status-badge st-${c.status === "ok" ? "approved" : "failed"}`}>
                          {c.status === "ok" ? t("Réussi") : t("Échec")}
                        </span>
                        {c.error && <div className="error call-error">{c.error}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data.calls.length < data.calls_total && (
            <div className="calls-more">
              <button className="btn" onClick={() => setLimit((n) => n + CALLS_PAGE)}>
                Afficher plus ({data.calls_total - data.calls.length} restant{data.calls_total - data.calls.length > 1 ? "s" : ""})
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}

/** Providers rencontrés depuis l'ouverture de la page : la liste ne rétrécit pas quand un filtre est appliqué. */
function useKnownProviders(data: CostsData | undefined, selected: string): string[] {
  const [known, setKnown] = useState<{ from?: CostsData; names: string[] }>({ names: [] });
  if (data && data !== known.from) {
    // ajustement pendant le rendu (pas d'effet) : https://react.dev/learn/you-might-not-need-an-effect
    const seen = [...Object.keys(data.by_provider), ...data.calls.map((c) => c.provider)];
    setKnown({ from: data, names: [...new Set([...known.names, ...seen])].sort() });
  }
  return selected && !known.names.includes(selected) ? [...known.names, selected] : known.names;
}

/** Barres horizontales d'une seule teinte, valeur et part écrites : la couleur ne porte aucune information seule. */
function Breakdown({
  title,
  rows,
  active,
  onSelect,
}: {
  title: string;
  rows: BreakdownRow[];
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="breakdown">
      <h2>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted">{t("Aucune dépense.")}</p>
      ) : (
        <ul>
          {rows.map((r) => (
            <li key={r.key}>
              <button
                className="breakdown-row"
                aria-pressed={active === r.key}
                title={t("{label} : {cost} ({share}). Cliquer pour filtrer.", { label: r.label, cost: usd.format(r.usd), share: formatShare(r.share) })}
                onClick={() => onSelect(active === r.key ? "" : r.key)}
              >
                <span className="breakdown-label">{r.label}</span>
                <span className="breakdown-value">
                  {usd.format(r.usd)} <span className="muted">{formatShare(r.share)}</span>
                </span>
                <span className="breakdown-track" aria-hidden>
                  {r.ratio > 0 && <span className="breakdown-bar" style={{ width: `${r.ratio * 100}%` }} />}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
