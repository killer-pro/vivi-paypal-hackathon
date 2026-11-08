import type { CreditEntry, CreditsBalance } from "./credits";
import { longDate } from "./format";
import type { Settings } from "./settings";
import { STEP_LABELS, type StepName } from "./steps";
import { locale, t } from "./i18n";

/** Un compte de `GET /api/admin/customers`. */
export interface Customer {
  id: number;
  email: string;
  role: "user" | "admin";
  verified: boolean;
  subscribed: boolean;
  subscription_ends_at: string | null;
  created_at: string;
  balance: CreditsBalance;
  /** Crédits réglés depuis l'inscription. */
  spent: number;
}

export interface CustomerList {
  total: number;
  customers: Customer[];
}

export interface CustomerDetail {
  customer: Customer;
  entries: CreditEntry[];
  next_before_id: number | null;
}

/** Une ligne de `GET /api/admin/margins` : `ratio` = revenu estimé ÷ coût de revient (`null` sans coût). */
export interface MarginRow {
  cost_usd: number;
  credits: number;
  revenue_usd: number;
  ratio: number | null;
}

export interface Margins {
  usd_per_credit: number;
  margin: number;
  rows: (MarginRow & { step: string })[];
  totals: MarginRow;
}

export type Bucket = "subscription" | "topup";

export interface AdjustBody {
  amount: number;
  bucket: Bucket;
  reason: string;
}

/** Corps de `POST /admin/customers/{id}/credits`, ou le message à afficher si la saisie est incorrecte. */
export function adjustBody(amount: string, bucket: Bucket, reason: string): AdjustBody | string {
  const value = Number(amount.trim().replace(/^\+/, ""));
  if (!/^[+-]?\d+$/.test(amount.trim()) || value === 0) return t("Le montant doit être un nombre entier de crédits, positif ou négatif.");
  if (!reason.trim()) return t("Indiquez le motif de l'ajustement.");
  return { amount: value, bucket, reason: reason.trim() };
}

export function planLabel(c: Customer): string {
  if (c.role === "admin") return "Administrateur";
  return c.subscribed && c.subscription_ends_at
    ? t("Abonné jusqu'au {date}", { date: longDate.format(new Date(c.subscription_ends_at)) })
    : t("Sans abonnement");
}

const ratioFormat = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });

/** Marge observée : « ×2,5 », ou « — » quand le coût de revient est nul. */
export function ratioLabel(ratio: number | null): string {
  return ratio === null ? "—" : `×${ratioFormat.format(ratio)}`;
}

/** Actions à tarif forfaitaire (clés de `flat_usd`) et exceptions de marge possibles (`+ clips`). */
export const FLAT_ACTIONS = ["idea", "story", "script", "reference", "voice", "final", "assist"] as const;
export const MARGIN_ACTIONS = [...FLAT_ACTIONS, "clips"] as const;
export const CLIP_PROFILES = ["fast", "balanced", "precision", "max"] as const;

type Table = Record<string, string>;

/** Saisie de l'écran Tarifs : tout en texte, la virgule décimale est acceptée. */
export interface PricingDraft {
  usdPerCredit: string;
  margin: string;
  signupGrant: string;
  marginOverrides: Table;
  flatUsd: Table;
  localClipUsd: Table;
}

const SIMPLE_KEYS = {
  usdPerCredit: "credits_usd_per_credit",
  margin: "credits_margin",
  signupGrant: "credits_signup_grant",
} as const;

function savedTable(settings: Settings): Record<string, Record<string, unknown>> {
  try {
    const table: unknown = JSON.parse(settings.credits_pricing || "{}");
    return table && typeof table === "object" ? (table as Record<string, Record<string, unknown>>) : {};
  } catch {
    return {};
  }
}

const strings = (section: Record<string, unknown> | undefined): Table =>
  Object.fromEntries(Object.entries(section ?? {}).map(([key, value]) => [key, String(value)]));

export function pricingDraft(settings: Settings): PricingDraft {
  const table = savedTable(settings);
  return {
    usdPerCredit: settings.credits_usd_per_credit ?? "",
    margin: settings.credits_margin ?? "",
    signupGrant: settings.credits_signup_grant ?? "",
    marginOverrides: strings(table.margin_overrides),
    flatUsd: strings(table.flat_usd),
    localClipUsd: strings(table.local_clip_usd),
  };
}

/** Nombre JSON si la saisie en est un, sinon le texte tel quel (le serveur le refusera avec un message clair). */
function amount(raw: string): number | string {
  const text = raw.trim().replace(",", ".");
  return text !== "" && Number.isFinite(Number(text)) ? Number(text) : text;
}

function section(table: Table): Record<string, number | string> {
  return Object.fromEntries(
    Object.entries(table)
      .filter(([, raw]) => raw.trim() !== "")
      .map(([key, raw]) => [key, amount(raw)]),
  );
}

/** Corps du `PUT /settings` : seulement ce qui a changé ; la table des tarifs est réécrite d'un bloc. */
export function pricingBody(saved: Settings, draft: PricingDraft): Settings {
  const body: Settings = {};
  for (const [field, key] of Object.entries(SIMPLE_KEYS)) {
    const value = draft[field as keyof typeof SIMPLE_KEYS].trim().replace(",", ".");
    if (value !== (saved[key] ?? "")) body[key] = value;
  }
  const table = {
    margin_overrides: section(draft.marginOverrides),
    flat_usd: section(draft.flatUsd),
    local_clip_usd: section(draft.localClipUsd),
  };
  const current = pricingDraft(saved);
  const before = {
    margin_overrides: section(current.marginOverrides),
    flat_usd: section(current.flatUsd),
    local_clip_usd: section(current.localClipUsd),
  };
  if (JSON.stringify(table) !== JSON.stringify(before)) body.credits_pricing = JSON.stringify(table);
  return body;
}

export const PROFILE_LABELS: Record<(typeof CLIP_PROFILES)[number], string> = {
  fast: "Rapide",
  balanced: t("Équilibré"),
  precision: t("Précision"),
  max: "Maximum",
};

/** Libellé d'une ligne du tableau des marges (`assist` : l'assistant IA, chat du plan compris). */
export function actionLabel(step: string): string {
  return step === "assist" ? t("Assistant IA") : step === "plan_chat" ? t("Chat du plan") : (STEP_LABELS[step as StepName] ?? step);
}
