import { describe, expect, it } from "vitest";
import { checkoutNotice, offerCaption, paypalNotice, paypalReturn, subscriptionStatus, type Billing } from "./billing";

const billing = (over: Partial<Billing> = {}): Billing => ({
  subscription: { credits: 400, label: "19 $ par mois", purchasable: true, paypal_purchasable: false },
  packs: [{ id: "pack200", credits: 200, label: "10 $", purchasable: true, paypal_purchasable: true }],
  subscribed: false,
  subscription_ends_at: null,
  manageable: false,
  ...over,
});

describe("offerCaption", () => {
  it("donne les crédits puis le prix", () => {
    expect(offerCaption({ credits: 200, label: "10 $" })).toBe("200 crédits · 10 $");
    expect(offerCaption({ credits: 1200, label: "55 $" }).replace(/\s/g, " ")).toBe("1 200 crédits · 55 $");
  });
  it("n'invente pas de prix quand le libellé manque", () => {
    expect(offerCaption({ credits: 200, label: "" })).toBe("200 crédits");
  });
});

describe("subscriptionStatus", () => {
  it("annonce la date de fin de période d'un abonné", () => {
    expect(subscriptionStatus(billing({ subscribed: true, subscription_ends_at: "2027-01-31T12:00:00Z" }))).toBe(
      "Abonné jusqu'au 31 janvier 2027",
    );
  });
  it("dit l'absence d'abonnement", () => {
    expect(subscriptionStatus(billing())).toBe("Pas d'abonnement");
  });
  it("ne donne pas de date à un abonné sans fin de période (compte administrateur)", () => {
    expect(subscriptionStatus(billing({ subscribed: true }))).toBe("Abonné");
  });
});

describe("checkoutNotice", () => {
  it("explique le retour de paiement", () => {
    expect(checkoutNotice("?checkout=success")).toContain("Paiement reçu");
    expect(checkoutNotice("?checkout=cancelled")).toContain("annulé");
  });
  it("ne dit rien sans retour de paiement", () => {
    expect(checkoutNotice("")).toBeNull();
    expect(checkoutNotice("?checkout=autre")).toBeNull();
  });
});

describe("paypalReturn", () => {
  it("lit la commande à capturer au retour d'un paiement approuvé", () => {
    expect(paypalReturn("?paypal=success&token=ORDER-1&PayerID=X")).toEqual({ status: "success", orderId: "ORDER-1" });
  });
  it("ignore un retour sans commande", () => {
    expect(paypalReturn("?paypal=success")).toBeNull();
  });
  it("reconnaît l'annulation et laisse passer le reste", () => {
    expect(paypalReturn("?paypal=cancelled&token=ORDER-1")).toEqual({ status: "cancelled" });
    expect(paypalReturn("?checkout=success")).toBeNull();
  });
});

describe("paypalNotice", () => {
  it("annonce les crédits ajoutés, ou un paiement déjà pris en compte", () => {
    expect(paypalNotice({ status: "success", orderId: "O" }, 200)).toContain("200 crédits");
    expect(paypalNotice({ status: "success", orderId: "O" }, 0)).toContain("déjà pris en compte");
  });
  it("patiente tant que la capture n'a pas répondu, et rassure en cas d'annulation", () => {
    expect(paypalNotice({ status: "success", orderId: "O" }, null)).toContain("confirmation");
    expect(paypalNotice({ status: "cancelled" }, null)).toContain("rien n'a été débité");
  });
});
