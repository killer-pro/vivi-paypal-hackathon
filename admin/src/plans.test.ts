import { describe, expect, it } from "vitest";
import type { Perks } from "./access";
import { perkLines, tierState } from "./plans";

const perks = (over: Partial<Perks> = {}): Perks => ({
  queue_max: 2,
  references_max: 4,
  profiles: ["balanced", "fast", "precision"],
  max_duration_s: 60,
  parallel_clips: 1,
  styles: true,
  ...over,
});

describe("perkLines", () => {
  it("perkLines lists every perk", () => {
    expect(perkLines(perks())).toEqual([
      "2 demandes en file par projet",
      "4 images de référence par projet",
      "Profils Rapide, Équilibré, Précision",
      "Vidéos jusqu'à 60 s",
      "1 clip généré à la fois",
      "Styles visuels",
    ]);
  });
  it("accorde au singulier et omet les styles absents", () => {
    const lines = perkLines(perks({ queue_max: 1, parallel_clips: 3, styles: false, profiles: ["max", "fast"] }));
    expect(lines).toContain("1 demande en file par projet");
    expect(lines).toContain("3 clips générés en même temps");
    expect(lines).toContain("Profils Rapide, Maximum");
    expect(lines).not.toContain("Styles visuels");
  });
});

describe("tierState", () => {
  it("tierState marks current tier", () => {
    expect(tierState({ id: "creator" }, "creator")).toBe("current");
    expect(tierState({ id: "starter" }, "creator")).toBe("available");
    expect(tierState({ id: "starter" }, null)).toBe("available");
  });
});
