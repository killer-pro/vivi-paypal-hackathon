import { describe, expect, it } from "vitest";
import { referenceBlocked, type Access } from "./access";

const access = (over: Partial<Access["locked"]> = {}, reason: string | null = "Réservé à l'abonnement : les images de référence"): Access => ({
  subscribed: false,
  subscription_ends_at: null,
  locked: { profiles: ["precision", "max"], reference: true, styles: ["anime"], ...over },
  reasons: { reference: reason, style: null },
});

describe("referenceBlocked", () => {
  it("donne le motif tant que l'image de référence est réservée", () => {
    expect(referenceBlocked(access())).toBe("Réservé à l'abonnement : les images de référence");
  });
  it("ne bloque rien pour un abonné, ni tant que l'accès n'est pas chargé", () => {
    expect(referenceBlocked(access({ reference: false }, null))).toBeUndefined();
    expect(referenceBlocked(undefined)).toBeUndefined();
  });
});
