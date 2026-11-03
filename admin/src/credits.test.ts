import { describe, expect, it } from "vitest";
import { canAfford, formatCredits, kindLabel, priceLabel, quoteShortfall, shortfall, type CreditsInfo, type PriceQuote } from "./credits";

const info = (total: number, unlimited = false): CreditsInfo => ({
  unlimited,
  balance: { subscription: 0, topup: total, total },
});

describe("formatCredits", () => {
  it("accorde le singulier et groupe les milliers", () => {
    expect(formatCredits(1)).toBe("1 crédit");
    expect(formatCredits(0)).toBe("0 crédit");
    expect(formatCredits(60)).toBe("60 crédits");
    expect(formatCredits(1200).replace(/\s/g, " ")).toBe("1 200 crédits");
  });
});

describe("canAfford", () => {
  it("compare le prix au solde total", () => {
    expect(canAfford(info(60), 60)).toBe(true);
    expect(canAfford(info(60), 61)).toBe(false);
  });
  it("ne limite jamais un compte illimité", () => {
    expect(canAfford(info(0, true), 5000)).toBe(true);
  });
});

describe("shortfall", () => {
  it("donne le manque, jamais négatif", () => {
    expect(shortfall(info(48), 60)).toBe(12);
    expect(shortfall(info(100), 60)).toBe(0);
    expect(shortfall(info(0, true), 60)).toBe(0);
  });
});

describe("kindLabel", () => {
  it("nomme chaque type de mouvement", () => {
    expect(kindLabel("signup_grant")).toBe("Crédits offerts");
    expect(kindLabel("reserve")).toBe("Réservation");
    expect(kindLabel("refund")).toBe("Remboursement");
    expect(kindLabel("adjust")).toBe("Ajustement");
    expect(kindLabel("topup")).toBe("Recharge");
    expect(kindLabel("subscription_grant")).toBe("Crédits d'abonnement");
    expect(kindLabel("expire")).toBe("Crédits expirés");
    expect(kindLabel("autre")).toBe("autre");
  });
});

describe("priceLabel", () => {
  const quote = (credits: number, unlimited = false, sufficient = true): PriceQuote => ({
    credits,
    balance: unlimited ? null : 100,
    sufficient,
    unlimited,
  });
  it("ajoute le prix au libellé du bouton", () => {
    expect(priceLabel("Générer les clips", quote(60))).toBe("Générer les clips · 60 crédits");
  });
  it("n'affiche rien pour une étape gratuite, un compte illimité ou un prix inconnu", () => {
    expect(priceLabel("Lancer le montage", quote(0))).toBe("Lancer le montage");
    expect(priceLabel("Générer", quote(60, true))).toBe("Générer");
    expect(priceLabel("Générer", null)).toBe("Générer");
  });
});

describe("quoteShortfall", () => {
  it("donne le manque d'un lancement, jamais négatif", () => {
    expect(quoteShortfall({ credits: 60, balance: 48, sufficient: false, unlimited: false })).toBe(12);
    expect(quoteShortfall({ credits: 60, balance: 100, sufficient: true, unlimited: false })).toBe(0);
    expect(quoteShortfall({ credits: 0, balance: null, sufficient: true, unlimited: true })).toBe(0);
  });
});
