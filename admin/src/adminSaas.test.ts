import { describe, expect, it } from "vitest";
import { adjustBody, planLabel, pricingBody, pricingDraft, ratioLabel, type Customer } from "./adminSaas";
import type { Settings } from "./settings";

const customer = (patch: Partial<Customer>): Customer => ({
  id: 1,
  email: "a@x.fr",
  role: "user",
  verified: true,
  subscribed: false,
  subscription_ends_at: null,
  created_at: "2026-11-02T10:00:00Z",
  balance: { subscription: 0, topup: 0, total: 0 },
  spent: 0,
  ...patch,
});

describe("adjustBody", () => {
  it("accepte un montant signé et nettoie le motif", () => {
    expect(adjustBody("-20", "topup", "  Reprise  ")).toEqual({ amount: -20, bucket: "topup", reason: "Reprise" });
    expect(adjustBody("+50", "subscription", "Geste")).toEqual({ amount: 50, bucket: "subscription", reason: "Geste" });
  });
  it("refuse un montant nul, décimal ou illisible, et un motif vide", () => {
    for (const bad of ["0", "1,5", "abc", ""]) expect(typeof adjustBody(bad, "topup", "x")).toBe("string");
    expect(adjustBody("5", "topup", "   ")).toBe("Indiquez le motif de l'ajustement.");
  });
});

describe("planLabel", () => {
  it("décrit l'offre du compte", () => {
    expect(planLabel(customer({ role: "admin" }))).toBe("Administrateur");
    expect(planLabel(customer({}))).toBe("Sans abonnement");
    expect(planLabel(customer({ subscribed: true, subscription_ends_at: "2026-12-02T00:00:00Z" }))).toMatch(/^Abonné jusqu'au .*2026/);
  });
});

describe("ratioLabel", () => {
  it("écrit la marge observée", () => {
    expect(ratioLabel(2.5)).toBe("×2,5");
    expect(ratioLabel(3)).toBe("×3");
    expect(ratioLabel(null)).toBe("—");
  });
});

const saved: Settings = {
  credits_usd_per_credit: "0.05",
  credits_margin: "2.5",
  credits_signup_grant: "100",
  credits_pricing: JSON.stringify({
    margin_overrides: { clips: 3 },
    flat_usd: { idea: 0.01 },
    local_clip_usd: { fast: 0.048 },
  }),
};

describe("pricingBody", () => {
  it("n'envoie rien sans modification", () => {
    expect(pricingBody(saved, pricingDraft(saved))).toEqual({});
  });
  it("n'envoie que les réglages simples modifiés, virgule acceptée", () => {
    const draft = { ...pricingDraft(saved), margin: "3,2", signupGrant: "150" };
    expect(pricingBody(saved, draft)).toEqual({ credits_margin: "3.2", credits_signup_grant: "150" });
  });
  it("réécrit la table des tarifs, une exception vidée est retirée", () => {
    const draft = pricingDraft(saved);
    draft.marginOverrides.clips = "";
    draft.marginOverrides.voice = "2";
    draft.flatUsd.idea = "0,02";
    draft.localClipUsd.max = "0.25";
    const table = JSON.parse(pricingBody(saved, draft).credits_pricing);
    expect(table).toEqual({
      margin_overrides: { voice: 2 },
      flat_usd: { idea: 0.02 },
      local_clip_usd: { fast: 0.048, max: 0.25 },
    });
  });
  it("transmet une saisie illisible telle quelle pour que le serveur la refuse", () => {
    const draft = pricingDraft(saved);
    draft.flatUsd.story = "abc";
    expect(JSON.parse(pricingBody(saved, draft).credits_pricing).flat_usd.story).toBe("abc");
  });
});
