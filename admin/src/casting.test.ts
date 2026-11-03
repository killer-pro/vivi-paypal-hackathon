import { describe, expect, it } from "vitest";
import type { Asset, ProjectDetail } from "./api";
import { castOf, sceneElements, sceneLink } from "./casting";

type CastProject = Pick<ProjectDetail, "steps" | "scenes" | "assets">;

const steps = (referenceStatus: string, story: unknown[] | null, references: unknown[] | null) =>
  [
    { name: "story", status: "approved", result: story ? { elements: story } : null },
    { name: "script", status: "approved", result: references ? { references } : null },
    { name: "reference", status: referenceStatus, result: null },
  ] as unknown as ProjectDetail["steps"];
const image = (ref: string): Asset => ({ id: 1, kind: "reference", meta: { ref }, url: `u-${ref}` }) as unknown as Asset;
const scene = (position: number, reference: string, elements: string[] = []) =>
  ({ position, reference, elements: elements.map((id) => ({ id, state: "" })) }) as unknown as ProjectDetail["scenes"][number];

const story = [
  { id: "kroc", kind: "character", name: "Kroc" },
  { id: "fries", kind: "prop", name: "Frites" },
  { id: "diner", kind: "place", name: "Diner" },
];
const references = [
  { id: "kroc", prompt: "p" },
  { id: "fries", prompt: "p" },
];
const project = (referenceStatus: string, assets: Asset[] = []): CastProject => ({
  steps: steps(referenceStatus, story, references),
  scenes: [scene(1, "kroc"), scene(2, "", ["fries"]), scene(3, "kroc", ["fries"])],
  assets,
});

describe("castOf", () => {
  it("donne l'image d'un élément prêt et le décompte de ses scènes, dont celles où il n'est qu'en elements", () => {
    const [kroc, fries] = castOf(project("approved", [image("kroc")]));
    expect(kroc).toEqual({ id: "kroc", name: "Kroc", kind: "character", status: "ready", imageUrl: "u-kroc", scenes: [1, 3] });
    expect(fries.scenes).toEqual([2, 3]);
  });

  it("suit l'étape reference pour un élément sans image", () => {
    expect(castOf(project("running"))[1].status).toBe("generating");
    expect(castOf(project("failed"))[1].status).toBe("failed");
    expect(castOf(project("pending"))[1].status).toBe("missing");
  });

  it("marque none un élément de l'histoire sans image prévue", () => {
    const diner = castOf(project("running"))[2];
    expect(diner).toEqual({ id: "diner", name: "Diner", kind: "place", status: "none", scenes: [] });
  });

  it("traite en accessoire un élément présent seulement dans references", () => {
    const only = { steps: steps("pending", null, [{ id: "x", prompt: "p" }]), scenes: [], assets: [] };
    expect(castOf(only)).toEqual([{ id: "x", name: "x", kind: "prop", status: "missing", scenes: [] }]);
  });

  it("est vide sans histoire ni references", () => {
    expect(castOf({ steps: steps("pending", null, null), scenes: [], assets: [] })).toEqual([]);
  });
});

describe("sceneLink", () => {
  const scenes = [
    { position: 1, continuity: "cut" as const },
    { position: 2, continuity: "continue" as const },
    { position: 3, continuity: "cut" as const },
  ];
  it("n'a pas de lien pour la première scène", () => {
    expect(sceneLink(scenes, 0)).toBeNull();
  });
  it("enchaîne sur la position de la scène précédente", () => {
    expect(sceneLink(scenes, 1)).toEqual({ kind: "chain", from: 1 });
  });
  it("coupe sans position source", () => {
    expect(sceneLink(scenes, 2)).toEqual({ kind: "cut" });
  });
  it("n'a pas de lien au-delà de la dernière scène", () => {
    expect(sceneLink(scenes, 3)).toBeNull();
  });
});

describe("sceneElements", () => {
  const cast = castOf(project("approved", [image("kroc")]));
  it("garde l'ordre et l'état de la scène, ignore un id inconnu", () => {
    const s = { elements: [{ id: "fries", state: "froides" }, { id: "ghost", state: "" }, { id: "kroc", state: "ravi" }] };
    expect(sceneElements(s, cast)).toEqual([
      { member: cast[1], state: "froides" },
      { member: cast[0], state: "ravi" },
    ]);
  });
});
