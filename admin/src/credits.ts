/** Solde d'un compte en crédits, deux lots (abonnement consommé en premier, puis rechargé). */
export interface CreditsBalance {
  subscription: number;
  topup: number;
  total: number;
}

/** Un mouvement du registre (`GET /api/credits`). */
export interface CreditEntry {
  id: number;
  kind: string;
  bucket: "subscription" | "topup";
  amount: number;
  reason: string;
  project_id: number | null;
  step: string | null;
  created_at: string;
}

/** Réponse de `GET /api/credits` ; `unlimited` : compte administrateur, que le solde ne limite pas. */
export interface CreditsInfo {
  unlimited: boolean;
  balance: CreditsBalance;
}

export interface CreditsPage extends CreditsInfo {
  entries: CreditEntry[];
  next_before_id: number | null;
}

/** Réponse de `POST /api/projects/{id}/steps/{étape}/price` : prix du lancement, solde du compte facturé. */
export interface PriceQuote {
  credits: number;
  balance: number | null;
  sufficient: boolean;
  unlimited: boolean;
}

const number = new Intl.NumberFormat("fr-FR");

/** « 1 crédit », « 1 200 crédits ». */
export function formatCredits(n: number): string {
  return `${number.format(n)} crédit${Math.abs(n) > 1 ? "s" : ""}`;
}

export function canAfford(info: CreditsInfo, price: number): boolean {
  return info.unlimited || info.balance.total >= price;
}

/** Crédits qui manquent pour payer `price` (0 si le solde suffit ou si le compte est illimité). */
export function shortfall(info: CreditsInfo, price: number): number {
  return info.unlimited ? 0 : Math.max(0, price - info.balance.total);
}

/** Crédits qui manquent pour payer le lancement chiffré par `quote`. */
export function quoteShortfall(quote: PriceQuote): number {
  return quote.unlimited || quote.balance === null ? 0 : Math.max(0, quote.credits - quote.balance);
}

const KIND_LABELS: Record<string, string> = {
  signup_grant: "Crédits offerts",
  reserve: "Réservation",
  refund: "Remboursement",
  adjust: "Ajustement",
  topup: "Recharge",
  subscription_grant: "Crédits d'abonnement",
  expire: "Crédits expirés",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

/** Libellé d'un bouton de lancement avec son prix : « Générer les clips · 60 crédits ». Rien d'ajouté pour une étape
 *  gratuite, un compte illimité ou tant que le prix n'est pas connu. */
export function priceLabel(label: string, quote: PriceQuote | null): string {
  return quote && !quote.unlimited && quote.credits > 0 ? `${label} · ${formatCredits(quote.credits)}` : label;
}
