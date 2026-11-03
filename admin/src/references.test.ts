import { describe, expect, it } from "vitest";
import { referenceElements, referenceImage, scenesUsing, storyElementsWithoutReference, type Asset } from "./api";
import type { Step } from "./steps";
import { chainBlockedReason, toggled } from "./studio";

const asset = (id: number, ref?: string): Asset =>
  ({ id, scene_id: null, kind: "reference", meta: ref ? { ref } : {}, url: `u${id}` }) as unknown as Asset;
const script = (result: Record<string, unknown> | null) => [{ name: "script", result }] as unknown as Step[];

describe("éléments de référence", () => {
  it("lit la liste du script, vide si absente ou invalide", () => {
    const elements = [{ id: "kroc", prompt: "p" }];
    expect(referenceElements(script({ references: elements }))).toEqual(elements);
    expect(referenceElements(script({ bible: "b" }))).toEqual([]);
    expect(referenceElements(script(null))).toEqual([]);
    expect(referenceElements(script({ references: "x" }))).toEqual([]);
  });

  it("prend la dernière image de chaque élément ; sans élément, celle du projet", () => {
    const assets = [asset(1), asset(2, "kroc"), asset(3, "kroc"), asset(4, "fries")];
    expect(referenceImage(assets, "kroc")?.id).toBe(3);
    expect(referenceImage(assets, "fries")?.id).toBe(4);
    expect(referenceImage(assets, "")?.id).toBe(1);
    expect(referenceImage(assets, "ghost")).toBeUndefined();
  });
});

describe("scènes d'un élément", () => {
  it("liste les positions des scènes qui prennent l'élément", () => {
    const scenes = [
      { position: 1, reference: "kroc", elements: [] },
      { position: 2, reference: "", elements: [] },
      { position: 3, reference: "kroc", elements: [] },
    ];
    expect(scenesUsing(scenes, "kroc")).toEqual([1, 3]);
    expect(scenesUsing(scenes, "ghost")).toEqual([]);
  });

  it("compte aussi les scènes qui n'ont l'élément qu'en image secondaire", () => {
    const scenes = [
      { position: 1, reference: "kroc", elements: [] },
      { position: 2, reference: "", elements: [{ id: "fries", state: "" }] },
      { position: 3, reference: "fries", elements: [{ id: "fries", state: "" }] },
    ];
    expect(scenesUsing(scenes, "fries")).toEqual([2, 3]);
  });
});

describe("choix des images d'une scène", () => {
  it("ajoute ou retire une image sans toucher aux autres", () => {
    expect(toggled(["a"], "c")).toEqual(["a", "c"]);
    expect(toggled(["a", "b"], "a")).toEqual(["b"]);
  });

  it("retire la plus ancienne quand la place manque", () => {
    expect(toggled(["a", "b"], "c")).toEqual(["b", "c"]);
  });
});

describe("éléments de l'histoire sans référence", () => {
  it("liste ceux qui n'ont pas d'image, avec leur prompt ou à défaut leur description", () => {
    const steps = [
      { name: "story", result: { elements: [
        { id: "kroc", name: "Kroc", prompt: "p1" },
        { id: "car", name: "Voiture", prompt: "une voiture", descriptor: "d" },
        { id: "cafe", name: "Café", prompt: "", descriptor: "un café" },
        { id: "vide", name: "", prompt: "", descriptor: "" },
      ] } },
      { name: "script", result: { references: [{ id: "kroc", prompt: "p1" }] } },
    ] as unknown as Step[];
    expect(storyElementsWithoutReference(steps)).toEqual([
      { id: "car", name: "Voiture", prompt: "une voiture" },
      { id: "cafe", name: "Café", prompt: "Café, un café" },
    ]);
    expect(storyElementsWithoutReference([])).toEqual([]);
  });
});

describe("scène enchaînée", () => {
  const scenes = [
    { position: 1, continuity: "cut" as const, selected_clip_asset_id: null },
    { position: 2, continuity: "continue" as const, selected_clip_asset_id: null },
  ];
  it("est bloquée tant que le clip de la scène précédente n'existe pas", () => {
    expect(chainBlockedReason(scenes, scenes[1])).toContain("scène 1");
    expect(chainBlockedReason([{ ...scenes[0], selected_clip_asset_id: 9 }, scenes[1]], scenes[1])).toBeNull();
  });
  it("ne bloque pas une scène coupée ni la première", () => {
    expect(chainBlockedReason(scenes, { position: 2, continuity: "cut" })).toBeNull();
    expect(chainBlockedReason(scenes, scenes[0])).toBeNull();
  });
});
