import { useEffect, useRef, useState } from "react";
import { api, errorMessage, useApi } from "../api";
import { checkoutNotice, offerCaption, paypalNotice, paypalReturn, subscriptionStatus, type Billing } from "../billing";
import "./BillingOffers.css";

/** Abonnement et recharges de la page Crédits : un clic ouvre la page de paiement Stripe ou PayPal ; les crédits
 *  n'arrivent qu'au webhook Stripe, ou à la capture PayPal faite au retour (le solde se recharge ensuite). */
export default function BillingOffers({ onPaid }: { onPaid: () => void }) {
  const { data: billing, error, reload } = useApi<Billing>("/billing");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const notice = checkoutNotice(window.location.search);
  const paid = window.location.search.includes("checkout=success");
  const returned = paypalReturn(window.location.search);
  const orderId = returned?.status === "success" ? returned.orderId : null;
  const [credited, setCredited] = useState<number | null>(null);

  const captured = useRef<string | null>(null);

  // Retour de PayPal : la commande approuvée se capture ici (et le webhook sert de filet si l'onglet se ferme avant).
  // Une seule capture par commande, même si l'effet est rejoué (mode strict de React, rechargement des données).
  useEffect(() => {
    if (!orderId || captured.current === orderId) return;
    captured.current = orderId;
    api<{ credited: number }>("/billing/paypal/capture", { method: "POST", body: JSON.stringify({ order_id: orderId }) })
      .then((r) => {
        setCredited((before) => Math.max(before ?? 0, r.credited));
        onPaid();
        reload();
      })
      .catch((err) => setFailure(errorMessage(err)));
  }, [orderId, onPaid, reload]);

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

  if (error) return <p className="error">{error}</p>;
  if (!billing) return null;
  const { subscription, packs } = billing;
  const message = returned ? paypalNotice(returned, credited) : notice;
  return (
    <section className="billing" aria-label="Abonnement et recharges">
      <div className="billing-head">
        <h2>Abonnement et recharges</h2>
        <span className="muted">{subscriptionStatus(billing)}</span>
        {billing.manageable && (
          <button className="btn btn-small btn-ghost" disabled={busy} onClick={() => go("/billing/portal")}>
            Gérer mes achats et mes factures
          </button>
        )}
      </div>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <div className="billing-offers">
        <div className="offer offer-main">
          <strong>Abonnement mensuel</strong>
          <span className="muted">{offerCaption(subscription)} · profils Précision et Maximum, images de référence, styles</span>
          <button
            className="btn btn-primary"
            disabled={busy || billing.subscribed || !subscription.purchasable}
            onClick={() => go("/billing/checkout", { kind: "subscription" })}
          >
            {billing.subscribed ? "Déjà abonné" : subscription.purchasable ? "S'abonner" : "Bientôt disponible"}
          </button>
        </div>
        {packs.map((pack) => (
          <div key={pack.id} className="offer">
            <strong>{offerCaption(pack)}</strong>
            <span className="muted">N'expirent jamais</span>
            <button
              className="btn"
              disabled={busy || !pack.purchasable}
              onClick={() => go("/billing/checkout", { kind: "topup", pack_id: pack.id })}
            >
              {pack.purchasable ? "Recharger" : pack.paypal_purchasable ? "Recharger par carte" : "Bientôt disponible"}
            </button>
            {pack.paypal_purchasable && (
              <button
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => go("/billing/paypal/order", { pack_id: pack.id })}
              >
                Payer avec PayPal
              </button>
            )}
          </div>
        ))}
      </div>
      {failure && (
        <p className="error" role="alert">
          {failure}
        </p>
      )}
    </section>
  );
}
