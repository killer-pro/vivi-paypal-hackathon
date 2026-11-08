import type { Perks } from "./access";
import { formatCredits } from "./credits";
import { longDate } from "./format";
import { t } from "./i18n";

/** Une offre payante : un forfait mensuel ou une recharge. `purchasable` : son prix Stripe est renseigné ;
 *  `paypal_purchasable` : un montant PayPal l'est. */
export interface Offer {
  credits: number;
  label: string;
  purchasable: boolean;
  paypal_purchasable: boolean;
}

/** Forfait mensuel : ses crédits, ses avantages et le nombre de vidéos de 30 s qu'ils paient. */
export interface Tier extends Offer {
  id: string;
  name: string;
  videos_30s: number;
  perks: Perks;
}

/** Réponse de `GET /api/billing`. `current_tier` : forfait de l'abonné ; `manageable` : le compte a un portail Stripe
 *  où gérer ses achats ; `paypal_cancellable` : il a un abonnement PayPal en cours, annulable depuis l'écran. */
export interface Billing {
  tiers: Tier[];
  free: { perks: Perks };
  current_tier: string | null;
  packs: (Offer & { id: string })[];
  subscribed: boolean;
  subscription_ends_at: string | null;
  manageable: boolean;
  paypal_cancellable: boolean;
}

const CANCELLED_NOTICE = t("Paiement annulé : rien n'a été débité.");


/** « 200 crédits · 10 $ » ; sans libellé de prix, les crédits seuls. */
export function offerCaption({ credits, label }: Pick<Offer, "credits" | "label">): string {
  return label ? `${formatCredits(credits)} · ${label}` : formatCredits(credits);
}

export function subscriptionStatus(billing: Billing): string {
  if (!billing.subscribed) return t("Pas d'abonnement");
  return billing.subscription_ends_at
    ? t("Abonné jusqu'au {date}", { date: longDate.format(new Date(billing.subscription_ends_at)) })
    : t("Abonné");
}

/** Message au retour de la page de paiement Stripe (`/plans?checkout=success|cancelled`) ; `null` sinon. */
export function checkoutNotice(search: string): string | null {
  switch (new URLSearchParams(search).get("checkout")) {
    case "success":
      return t("Paiement reçu : vos crédits arrivent dans quelques secondes.");
    case "cancelled":
      return CANCELLED_NOTICE;
    default:
      return null;
  }
}

/** Retour de PayPal sur `/plans` : `?paypal=success&token=<commande>` (à capturer) ou `?paypal=cancelled` ; `null` sinon. */
export type PayPalReturn = { status: "success"; orderId: string } | { status: "cancelled" };

export function paypalReturn(search: string): PayPalReturn | null {
  const params = new URLSearchParams(search);
  const orderId = params.get("token");
  if (params.get("paypal") === "success" && orderId) return { status: "success", orderId };
  return params.get("paypal") === "cancelled" ? { status: "cancelled" } : null;
}

/** Message affiché une fois la capture PayPal tentée : `credited` crédits ajoutés (0 : déjà crédités). */
export function paypalNotice(outcome: PayPalReturn, credited: number | null): string {
  if (outcome.status === "cancelled") return CANCELLED_NOTICE;
  if (credited === null) return t("Paiement PayPal en cours de confirmation…");
  return credited > 0 ? t("Paiement reçu : {credits} ajoutés à votre solde.", { credits: formatCredits(credited) }) : t("Paiement déjà pris en compte.");
}

/** Retour de PayPal après l'abonnement : `?paypal_sub=success&subscription_id=<abonnement>` (à confirmer) ou
 *  `?paypal_sub=cancelled` ; `null` sinon. */
export type PayPalSubscriptionReturn = { status: "success"; subscriptionId: string } | { status: "cancelled" };

export function paypalSubscriptionReturn(search: string): PayPalSubscriptionReturn | null {
  const params = new URLSearchParams(search);
  const subscriptionId = params.get("subscription_id");
  if (params.get("paypal_sub") === "success" && subscriptionId) return { status: "success", subscriptionId };
  return params.get("paypal_sub") === "cancelled" ? { status: "cancelled" } : null;
}

/** Réponse de `POST /api/billing/paypal/subscription/confirm` : `activated` faux tant que le premier mois n'est pas prélevé. */
export interface SubscriptionConfirmation {
  activated: boolean;
  credited: number;
}

/** Message affiché une fois l'abonnement PayPal confirmé (`null` : la confirmation n'a pas encore répondu). */
export function paypalSubscriptionNotice(outcome: PayPalSubscriptionReturn, result: SubscriptionConfirmation | null): string {
  if (outcome.status === "cancelled") return CANCELLED_NOTICE;
  if (!result?.activated) return t("Abonnement PayPal en cours de confirmation…");
  return result.credited > 0
    ? t("Abonnement activé : {credits} ajoutés à votre solde.", { credits: formatCredits(result.credited) })
    : t("Abonnement déjà pris en compte.");
}
