import { formatCredits } from "./credits";
import { longDate } from "./format";

/** Une offre payante : l'abonnement mensuel ou une recharge. `purchasable` : son prix Stripe est renseigné ;
 *  `paypal_purchasable` : un montant PayPal l'est. */
export interface Offer {
  credits: number;
  label: string;
  purchasable: boolean;
  paypal_purchasable: boolean;
}

/** Réponse de `GET /api/billing`. `manageable` : le compte a un portail Stripe où gérer ses achats. */
export interface Billing {
  subscription: Offer;
  packs: (Offer & { id: string })[];
  subscribed: boolean;
  subscription_ends_at: string | null;
  manageable: boolean;
}


/** « 200 crédits · 10 $ » ; sans libellé de prix, les crédits seuls. */
export function offerCaption({ credits, label }: Pick<Offer, "credits" | "label">): string {
  return label ? `${formatCredits(credits)} · ${label}` : formatCredits(credits);
}

export function subscriptionStatus(billing: Billing): string {
  if (!billing.subscribed) return "Pas d'abonnement";
  return billing.subscription_ends_at
    ? `Abonné jusqu'au ${longDate.format(new Date(billing.subscription_ends_at))}`
    : "Abonné";
}

/** Message au retour de la page de paiement Stripe (`/credits?checkout=success|cancelled`) ; `null` sinon. */
export function checkoutNotice(search: string): string | null {
  switch (new URLSearchParams(search).get("checkout")) {
    case "success":
      return "Paiement reçu : vos crédits arrivent dans quelques secondes.";
    case "cancelled":
      return "Paiement annulé : rien n'a été débité.";
    default:
      return null;
  }
}

/** Retour de PayPal sur `/credits` : `?paypal=success&token=<commande>` (à capturer) ou `?paypal=cancelled` ; `null` sinon. */
export type PayPalReturn = { status: "success"; orderId: string } | { status: "cancelled" };

export function paypalReturn(search: string): PayPalReturn | null {
  const params = new URLSearchParams(search);
  const orderId = params.get("token");
  if (params.get("paypal") === "success" && orderId) return { status: "success", orderId };
  return params.get("paypal") === "cancelled" ? { status: "cancelled" } : null;
}

/** Message affiché une fois la capture PayPal tentée : `credited` crédits ajoutés (0 : déjà crédités). */
export function paypalNotice(outcome: PayPalReturn, credited: number | null): string {
  if (outcome.status === "cancelled") return "Paiement annulé : rien n'a été débité.";
  if (credited === null) return "Paiement PayPal en cours de confirmation…";
  return credited > 0 ? `Paiement reçu : ${formatCredits(credited)} ajoutés à votre solde.` : "Paiement déjà pris en compte.";
}
