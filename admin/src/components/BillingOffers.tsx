import { useEffect, useRef, useState } from "react";
import { api, errorMessage, useApi } from "../api";
import {
  checkoutNotice,
  offerCaption,
  paypalNotice,
  paypalReturn,
  paypalSubscriptionNotice,
  paypalSubscriptionReturn,
  subscriptionStatus,
  type Billing,
  type SubscriptionConfirmation,
} from "../billing";
import { formatCredits } from "../credits";
import { perkLines, tierState } from "../plans";
import { serverText } from "../serverText";
import { CheckIcon } from "./icons";
import { useConfirm } from "../hooks/useConfirm";
import "./BillingOffers.css";
import { t, tn } from "../i18n";

const STRIP_MAX = 30;

const SUBSCRIPTION_CANCELLED = t("Abonnement PayPal annulé : la période déjà payée reste acquise.");

/** Une seule confirmation par retour de PayPal (commande ou abonnement), même si l'effet est rejoué (mode strict de
 *  React, rechargement des données). */
function useConfirmOnce(id: string | null, run: (id: string) => void) {
  const done = useRef<string | null>(null);
  useEffect(() => {
    if (!id || done.current === id) return;
    done.current = id;
    run(id);
  }, [id, run]);
}

/** Forfaits et recharges de la page Forfaits : un clic ouvre la page de paiement Stripe ou PayPal ; les crédits
 *  n'arrivent qu'au webhook Stripe, ou à la capture (recharge) ou confirmation (abonnement) PayPal faite au retour sur
 *  `/plans` (le solde se recharge ensuite). */
export default function BillingOffers({ onPaid }: { onPaid: () => void }) {
  const { data: billing, error, reload } = useApi<Billing>("/billing");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const notice = checkoutNotice(window.location.search);
  const paid = window.location.search.includes("checkout=success");
  const returned = paypalReturn(window.location.search);
  const orderId = returned?.status === "success" ? returned.orderId : null;
  const [credited, setCredited] = useState<number | null>(null);
  const returnedSub = paypalSubscriptionReturn(window.location.search);
  const subscriptionId = returnedSub?.status === "success" ? returnedSub.subscriptionId : null;
  const [confirmation, setConfirmation] = useState<SubscriptionConfirmation | null>(null);
  const [cancelledSub, setCancelledSub] = useState(false);
  const { confirm, dialog } = useConfirm();

  // Retour de PayPal : la commande approuvée se capture ici (et le webhook sert de filet si l'onglet se ferme avant).
  useConfirmOnce(orderId, (id) =>
    api<{ credited: number }>("/billing/paypal/capture", { method: "POST", body: JSON.stringify({ order_id: id }) })
      .then((r) => {
        setCredited((before) => Math.max(before ?? 0, r.credited));
        onPaid();
        reload();
      })
      .catch((err) => setFailure(errorMessage(err))),
  );

  // Retour de PayPal après l'abonnement : le premier mois prélevé crédite le quota (le webhook sert de filet).
  useConfirmOnce(subscriptionId, (id) =>
    api<SubscriptionConfirmation>("/billing/paypal/subscription/confirm", {
      method: "POST",
      body: JSON.stringify({ subscription_id: id }),
    })
      .then((r) => {
        setConfirmation(r);
        onPaid();
        reload();
      })
      .catch((err) => setFailure(errorMessage(err))),
  );

  // Retour de paiement : le webhook peut arriver après la redirection, le solde est relu quelques fois.
  useEffect(() => {
    if (!paid) return;
    const timers = [2000, 5000, 10000].map((ms) =>
      setTimeout(() => {
        onPaid();
        reload();
      }, ms),
    );
    return () => timers.forEach(clearTimeout);
  }, [paid, onPaid, reload]);

  async function go(path: string, body?: object) {
    setBusy(true);
    setFailure(null);
    try {
      const { url } = await api<{ url: string }>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      window.location.assign(url);
    } catch (err) {
      setFailure(errorMessage(err));
      setBusy(false);
    }
  }

  async function cancelSubscription() {
    setBusy(true);
    setFailure(null);
    try {
      await api("/billing/paypal/subscription/cancel", { method: "POST" });
      setCancelledSub(true);
      reload();
    } catch (err) {
      setFailure(errorMessage(err));
    }
    setBusy(false);
  }

  if (error) return <p className="error">{error}</p>;
  if (!billing) return null;
  const message = cancelledSub
    ? SUBSCRIPTION_CANCELLED
    : returnedSub
      ? paypalSubscriptionNotice(returnedSub, confirmation)
      : returned
        ? paypalNotice(returned, credited)
        : notice;
  return (
    <>
      <p className="plans-status muted">
        {subscriptionStatus(billing)}
        {billing.manageable && (
          <button className="btn btn-small btn-ghost" disabled={busy} onClick={() => go("/billing/portal")}>
            {t("Gérer mes achats et mes factures")}
          </button>
        )}
      </p>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {failure && (
        <p className="error" role="alert">
          {failure}
        </p>
      )}

      <section className="plans-tiers" aria-label={t("Forfaits mensuels")}>
        {billing.tiers.map((tier) => {
          const current = tierState(tier, billing.current_tier) === "current";
          return (
            <article key={tier.id} className={`plan-card${current ? " is-current" : ""}`} aria-current={current || undefined}>
              <header className="plan-card-head">
                <h2>{t(tier.name)}</h2>
                {current && <span className="plan-card-badge">{t("Votre forfait")}</span>}
              </header>
              <p className="plan-card-price">{serverText(tier.label)}</p>
              <p className="muted">{t("{credits} par mois", { credits: formatCredits(tier.credits) })}</p>
              <VideoStrip count={tier.videos_30s} />
              <ul className="plan-perks">
                {perkLines(tier.perks).map((line) => (
                  <li key={line}>
                    <CheckIcon /> {line}
                  </li>
                ))}
              </ul>
              <div className="plan-card-actions">
                {current ? (
                  billing.paypal_cancellable ? (
                    <button
                      className="btn btn-ghost"
                      disabled={busy}
                      onClick={() =>
                        confirm({
                          title: t("Arrêter l'abonnement ?"),
                          message: t(
                            "Il ne sera plus renouvelé. Votre forfait et ses crédits restent jusqu'à la fin de la période déjà payée.",
                          ),
                          confirmLabel: t("Arrêter le renouvellement"),
                          onConfirm: cancelSubscription,
                        })
                      }
                    >
                      {t("Annuler mon abonnement PayPal")}
                    </button>
                  ) : (
                    <span className="muted">{t("Forfait actuel")}</span>
                  )
                ) : billing.subscribed && tier.paypal_purchasable ? (
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() =>
                      confirm({
                        title: t("Passer au forfait {name} ?", { name: t(tier.name) }),
                        message: t(
                          "Le nouveau forfait démarre dès le paiement validé chez PayPal : {price}, {credits} qui remplacent les crédits d'abonnement restants (vos recharges sont gardées). L'abonnement actuel est arrêté, sans remboursement du mois en cours.",
                          { price: serverText(tier.label), credits: formatCredits(tier.credits) },
                        ),
                        confirmLabel: t("Continuer vers PayPal"),
                        onConfirm: () => go("/billing/paypal/subscription", { tier_id: tier.id }),
                      })
                    }
                  >
                    {t("Passer à ce forfait")}
                  </button>
                ) : billing.subscribed ? (
                  <span className="muted">{t("Pour changer, annulez votre forfait : le nouveau commence à la fin de la période.")}</span>
                ) : tier.paypal_purchasable ? (
                  <button className="btn" disabled={busy} onClick={() => go("/billing/paypal/subscription", { tier_id: tier.id })}>
                    {t("S'abonner avec PayPal")}
                  </button>
                ) : (
                  <button
                    className="btn"
                    disabled={busy || !tier.purchasable}
                    onClick={() => go("/billing/checkout", { kind: "subscription", tier_id: tier.id })}
                  >
                    {tier.purchasable ? t("S'abonner par carte") : t("Bientôt disponible")}
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </section>

      <p className="plans-free">
        <strong>{t("Sans abonnement")}</strong>{" "}
        <span className="muted">{perkLines(billing.free.perks).join(" ; ")}.</span>
      </p>

      <section className="plans-packs" aria-labelledby="packs-title">
        <h2 id="packs-title">{t("Recharges")}</h2>
        <p className="muted">{t("Crédits sans abonnement, qui n'expirent jamais : avantages du niveau gratuit.")}</p>
        <div className="billing-offers">
          {billing.packs.map((pack) => (
            <div key={pack.id} className="offer">
              <strong>{offerCaption(pack)}</strong>
              {pack.paypal_purchasable ? (
                <button className="btn" disabled={busy} onClick={() => go("/billing/paypal/order", { pack_id: pack.id })}>
                  {t("Payer avec PayPal")}
                </button>
              ) : (
                <button
                  className="btn"
                  disabled={busy || !pack.purchasable}
                  onClick={() => go("/billing/checkout", { kind: "topup", pack_id: pack.id })}
                >
                  {pack.purchasable ? t("Recharger par carte") : t("Bientôt disponible")}
                </button>
              )}
            </div>
          ))}
        </div>
      </section>
      {dialog}
    </>
  );
}

/** Ce que paient les crédits du mois, en cadres 9:16 : un par vidéo de 30 s (30 au plus, le reste en nombre). */
function VideoStrip({ count }: { count: number }) {
  const shown = Math.min(count, STRIP_MAX);
  return (
    <div className="plan-strip">
      <span className="plan-strip-frames" aria-hidden="true">
        {Array.from({ length: shown }, (_, i) => (
          <span key={i} />
        ))}
        {count > shown && <span className="plan-strip-more">+{count - shown}</span>}
      </span>
      <span>{tn(count, "≈ {n} vidéo de 30 s", "≈ {n} vidéos de 30 s")}</span>
    </div>
  );
}
