import { describe, expect, it } from "vitest";
import type { Scene } from "./api";
import { firstBlank, moved, newScene, planTotal, toDraft, withoutAt, type DraftScene } from "./plan";

const draft = (voice: string, visual = "plan", duration = 3, key = voice): DraftScene => ({
  key,
  voice_text: voice,
  visual_prompt: visual,
  duration_s: duration,
});

describe("moved", () => {
  it("échange deux scènes voisines", () => {
    const list = [draft("a"), draft("b"), draft("c")];
    expect(moved(list, 1, -1).map((s) => s.key)).toEqual(["b", "a", "c"]);
    expect(moved(list, 1, 1).map((s) => s.key)).toEqual(["a", "c", "b"]);
  });

  it("ne dépasse pas les bornes", () => {
    const list = [draft("a"), draft("b")];
    expect(moved(list, 0, -1)).toEqual(list);
    expect(moved(list, 1, 1)).toEqual(list);
  });
});

describe("firstBlank", () => {
  it("renvoie la première scène sans voix ou sans prompt (espaces compris)", () => {
    expect(firstBlank([draft("a"), draft("b", "  ")])).toBe(1);
    expect(firstBlank([draft(" "), draft("b")])).toBe(0);
  });

  it("renvoie -1 quand tout est rempli", () => {
    expect(firstBlank([draft("a"), draft("b")])).toBe(-1);
  });
});

describe("planTotal", () => {
  it("additionne les durées et ignore celles qui ne sont pas des nombres", () => {
    expect(planTotal([draft("a", "p", 3), draft("b", "p", NaN), draft("c", "p", 2.5)])).toBe(5.5);
  });
});

describe("toDraft", () => {
  it("garde l'id et donne une clé stable par scène", () => {
    const scene = { id: 7, position: 1, voice_text: "v", visual_prompt: "p", duration_s: 4, selected_clip_asset_id: 9 };
    expect(toDraft([scene as Scene])).toEqual([
      { id: 7, key: "scene-7", voice_text: "v", visual_prompt: "p", duration_s: 4 },
    ]);
  });
});

describe("withoutAt / newScene", () => {
  it("retire la scène à l'index donné", () => {
    expect(withoutAt([draft("a"), draft("b")], 0).map((s) => s.key)).toEqual(["b"]);
  });

  it("crée une scène vide de 3 s avec une clé unique", () => {
    const [a, b] = [newScene(), newScene()];
    expect(a).toMatchObject({ voice_text: "", visual_prompt: "", duration_s: 3 });
    expect(a.key).not.toBe(b.key);
    expect(a.id).toBeUndefined();
  });
});
