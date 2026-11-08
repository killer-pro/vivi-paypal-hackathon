import { useState, type FormEvent, type ReactNode } from "react";
import { api, errorMessage, useApi } from "../api";
import { ErrorState, Field } from "../components/ui";
import {
  actionLabel,
  CLIP_PROFILES,
  FLAT_ACTIONS,
  MARGIN_ACTIONS,
  PROFILE_LABELS,
  pricingBody,
  pricingDraft,
  ratioLabel,
  type Margins,
  type PricingDraft,
} from "../adminSaas";
import { formatCredits } from "../credits";
import type { Settings } from "../settings";
import { usd } from "../format";
import "./Pricing.css";
import { t } from "../i18n";

const PERIODS = [
  { days: 7, label: "7 derniers jours" },
  { days: 30, label: "30 derniers jours" },
  { days: 0, label: t("Depuis le début") },
];

/** Tarifs du crédit (valeur, marge, exceptions, coûts de revient) et tableau coût de revient vs crédits facturés. */
export default function Pricing() {
  const settings = useApi<Settings>("/settings");
  if (settings.error) return <ErrorState message={settings.error} onRetry={settings.reload} />;
  if (!settings.data) return <p className="muted">{t("Chargement…")}</p>;
  return (
    <>
      <header className="page-head">
        <h1>{t("Tarifs")}</h1>
      </header>
      <MarginsTable />
      <PricingForm initial={settings.data} />
    </>
  );
}

function MarginsTable() {
  const [days, setDays] = useState(30);
  // Le début de période est fixé une fois par choix (et non à chaque rendu) pour ne pas relancer la requête en boucle.
  const [since, setSince] = useState(() => sinceOf(30));
  const { data, error, reload } = useApi<Margins>(`/admin/margins${since ? `?since=${encodeURIComponent(since)}` : ""}`);
  return (
    <section aria-labelledby="margins-title" className="pricing-block">
      <div className="pricing-head">
        <h2 id="margins-title">{t("Marges observées")}</h2>
        <select
          className="input"
          aria-label={t("Période")}
          value={days}
          onChange={(e) => {
            setDays(Number(e.target.value));
            setSince(sinceOf(Number(e.target.value)));
          }}
        >
          {PERIODS.map((p) => (
            <option key={p.days} value={p.days}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
      {error && <ErrorState message={error} onRetry={reload} />}
      {data && (
        <>
          <p className="muted">
            {t("Revenu estimé au prix nominal du crédit ({price}) ; marge visée ×{margin}. Les projets de l'administrateur ne comptent pas.", { price: usd.format(data.usd_per_credit), margin: data.margin })}
          </p>
          {data.rows.length === 0 ? (
            <p className="muted">{t("Aucune génération facturée sur la période.")}</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("Action")}</th>
                    <th className="num">{t("Coût de revient")}</th>
                    <th className="num">{t("Crédits facturés")}</th>
                    <th className="num">{t("Revenu estimé")}</th>
                    <th className="num">{t("Marge observée")}</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.rows, { step: "", ...data.totals }].map((r) => (
                    <tr key={r.step || "total"} className={r.step ? undefined : "pricing-total"}>
                      <td>{r.step ? actionLabel(r.step) : "Total"}</td>
                      <td className="num">{usd.format(r.cost_usd)}</td>
                      <td className="num">{formatCredits(r.credits)}</td>
                      <td className="num">{usd.format(r.revenue_usd)}</td>
                      <td className={`num ${r.ratio !== null && r.ratio < data.margin ? "pricing-low" : ""}`}>{ratioLabel(r.ratio)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

const sinceOf = (days: number) => (days ? new Date(Date.now() - days * 86_400_000).toISOString() : "");

function PricingForm({ initial }: { initial: Settings }) {
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState(() => pricingDraft(initial));
  const [status, setStatus] = useState<{ error?: string; done?: boolean }>({});
  const [busy, setBusy] = useState(false);
  const body = pricingBody(saved, draft);
  const dirty = Object.keys(body).length > 0;

  const edit = (patch: Partial<PricingDraft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setStatus({});
  };
  const editTable = (table: "marginOverrides" | "flatUsd" | "localClipUsd", key: string, value: string) =>
    edit({ [table]: { ...draft[table], [key]: value } });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const next = await api<Settings>("/settings", { method: "PUT", body: JSON.stringify(body) });
      setSaved(next);
      setDraft(pricingDraft(next));
      setStatus({ done: true });
    } catch (err) {
      setStatus({ error: errorMessage(err) });
    }
    setBusy(false);
  }

  const group = (title: string, hint: ReactNode, children: ReactNode) => (
    <fieldset className="pricing-group">
      <legend>{title}</legend>
      <p className="muted">{hint}</p>
      <div className="pricing-grid">{children}</div>
    </fieldset>
  );
  const num = (label: string, value: string, onChange: (v: string) => void, placeholder?: string) => (
    <Field label={label} key={label}>
      <input className="input" inputMode="decimal" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );

  return (
    <form className="pricing-block" onSubmit={submit}>
      <h2>{t("Réglages des tarifs")}</h2>
      {group(
        t("Crédit et marge"),
        t("Prix en crédits = coût de revient × marge ÷ valeur du crédit, arrondi au crédit supérieur."),
        <>
          {num(t("Valeur d'un crédit ($)"), draft.usdPerCredit, (v) => edit({ usdPerCredit: v }))}
          {num("Marge globale (×)", draft.margin, (v) => edit({ margin: v }))}
          {num(t("Crédits offerts à l'inscription"), draft.signupGrant, (v) => edit({ signupGrant: v }))}
        </>,
      )}
      {group(
        t("Exceptions de marge"),
        t("Vide : la marge globale s'applique."),
        MARGIN_ACTIONS.map((a) =>
          num(actionLabel(a), draft.marginOverrides[a] ?? "", (v) => editTable("marginOverrides", a, v), "globale"),
        ),
      )}
      {group(
        t("Coût de revient forfaitaire ($)"),
        t("Coût d'une action (la voix : par scène). Les clips viennent du coût réel du provider ou du forfait local."),
        FLAT_ACTIONS.map((a) => num(actionLabel(a), draft.flatUsd[a] ?? "", (v) => editTable("flatUsd", a, v))),
      )}
      {group(
        t("Clip local, par profil ($ pour 3 s)"),
        t("Coût interne d'un clip ComfyUI : serveur, électricité, amortissement."),
        CLIP_PROFILES.map((p) => num(PROFILE_LABELS[p], draft.localClipUsd[p] ?? "", (v) => editTable("localClipUsd", p, v))),
      )}
      {status.error && (
        <p className="error" role="alert">
          {status.error}
        </p>
      )}
      {status.done && <p className="muted">{t("Tarifs enregistrés : ils s'appliquent aux prochains lancements.")}</p>}
      <button className="btn btn-primary" disabled={!dirty || busy}>
        {t("Enregistrer les tarifs")}
      </button>
    </form>
  );
}
