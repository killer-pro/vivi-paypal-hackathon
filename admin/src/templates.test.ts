import { describe, expect, it } from "vitest";
import { DURATIONS } from "./newVideo";
import { PLACEHOLDER, placeholderRange, TEMPLATES } from "./templates";

describe("TEMPLATES", () => {
  it("ont des identifiants uniques et des textes non vides", () => {
    expect(new Set(TEMPLATES.map((t) => t.id)).size).toBe(TEMPLATES.length);
    for (const t of TEMPLATES) expect([t.name, t.hint, t.subject].every((s) => s.trim().length > 0)).toBe(true);
  });
  it("réglent une durée que le formulaire propose", () => {
    for (const t of TEMPLATES) expect(DURATIONS).toContain(t.duration_s);
  });
  it("laissent exactement un marqueur à remplacer, et une durée de scène qui tient dans la vidéo", () => {
    for (const t of TEMPLATES) {
      expect(t.subject.split(PLACEHOLDER)).toHaveLength(2);
      if (t.scene_length_s !== null) expect(t.duration_s / t.scene_length_s).toBeGreaterThanOrEqual(3);
    }
  });
});

describe("placeholderRange", () => {
  it("donne la plage du marqueur", () => {
    const text = "3 astuces pour [sujet], ton direct";
    const range = placeholderRange(text);
    expect(range && text.slice(range[0], range[1])).toBe(PLACEHOLDER);
  });
  it("renvoie null sans marqueur", () => {
    expect(placeholderRange("3 astuces pour dormir")).toBeNull();
  });
});
