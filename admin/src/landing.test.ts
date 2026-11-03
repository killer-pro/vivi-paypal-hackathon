import { describe, expect, it } from "vitest";
import { moveScene, nextScene, PIPELINE, SCENE_IDS, SCENES, STYLES, FORMATS, USE_CASES, WALL } from "./landing";

describe("moveScene", () => {
  it("échange la scène avec sa voisine", () => {
    expect(moveScene(SCENE_IDS, "sneaker-detail", -1)).toEqual(["sneaker-detail", "sneaker-packshot", "sneaker-street"]);
    expect(moveScene(SCENE_IDS, "sneaker-packshot", 1)).toEqual(["sneaker-detail", "sneaker-packshot", "sneaker-street"]);
  });

  it("ne change rien aux extrémités", () => {
    expect(moveScene(SCENE_IDS, "sneaker-packshot", -1)).toBe(SCENE_IDS);
    expect(moveScene(SCENE_IDS, "sneaker-street", 1)).toBe(SCENE_IDS);
  });

  it("ne modifie pas l'ordre d'origine", () => {
    moveScene(SCENE_IDS, "sneaker-detail", 1);
    expect(SCENE_IDS).toEqual(["sneaker-packshot", "sneaker-detail", "sneaker-street"]);
  });
});

describe("nextScene", () => {
  it("suit l'ordre de lecture puis reprend au début", () => {
    expect(nextScene(["sneaker-street", "sneaker-packshot", "sneaker-detail"], "sneaker-street")).toBe("sneaker-packshot");
    expect(nextScene(["sneaker-street", "sneaker-packshot", "sneaker-detail"], "sneaker-detail")).toBe("sneaker-street");
  });
});

describe("SCENES", () => {
  it("décrit chaque scène", () => {
    expect(Object.keys(SCENES).sort()).toEqual([...SCENE_IDS].sort());
  });
});

describe("PIPELINE", () => {
  it("donne à chaque étape sa propre image", () => {
    const arts = PIPELINE.map((step) => step.art);
    expect(new Set(arts).size).toBe(PIPELINE.length);
  });
});

describe("USE_CASES, STYLES, FORMATS et WALL", () => {
  it("le mur montre chaque clip une seule fois, et tous les clips des sections", () => {
    const wall = WALL.flat();
    expect(new Set(wall).size).toBe(wall.length);
    const shown = [...USE_CASES, ...STYLES, ...FORMATS].map((u) => u.art);
    expect(new Set(shown).size).toBe(shown.length);
    for (const name of [...shown, ...SCENE_IDS]) expect(wall).toContain(name);
  });
});
