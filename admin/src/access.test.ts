import { describe, expect, it } from "vitest";
import { queueMax, referenceElementsOf, referenceLimit, type Access } from "./access";

const access = (references_max = 2, queue_max = 1): Access => ({
  subscribed: false,
  subscription_ends_at: null,
  tier: null,
  perks: { queue_max, references_max, profiles: ["fast", "balanced"], max_duration_s: 30, parallel_clips: 1, styles: false },
  locked: { profiles: ["precision", "max"], styles: ["anime"] },
  reasons: { style: null },
});

describe("referenceLimit", () => {
  it("donne le motif au-delà du nombre d'éléments du forfait", () => {
    expect(referenceLimit(access(), 3)).toBe("Limite de votre forfait : 2 images de référence");
  });
  it("laisse passer dans la limite, et tant que l'accès n'est pas chargé", () => {
    expect(referenceLimit(access(), 2)).toBeUndefined();
    expect(referenceLimit(undefined, 99)).toBeUndefined();
  });
});

describe("referenceElementsOf", () => {
  it("compte les éléments distincts, l'image du projet pour un", () => {
    const asset = (ref?: string) => ({ kind: "reference", meta: ref === undefined ? {} : { ref } });
    expect(referenceElementsOf([asset(), asset("lea"), asset("lea"), { kind: "clip", meta: {} }])).toEqual(new Set(["", "lea"]));
  });
});

describe("queueMax", () => {
  it("suit le forfait, une demande tant que l'accès n'est pas chargé", () => {
    expect(queueMax(access(2, 4))).toBe(4);
    expect(queueMax(undefined)).toBe(1);
  });
});
