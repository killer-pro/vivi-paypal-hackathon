import { describe, expect, it } from "vitest";
import { blankBeat, elementCounts, speakingElements, newBeat, newElement, storyOf, storyTotal, toResult, unknownIds, withoutElement, type DraftStory } from "./story";

const chloe = { id: "chloe", kind: "character", name: "Chloe", descriptor: "Chloe, 22", prompt: "Chloe alone", voice_id: "" } as const;
const sac = { id: "sac", kind: "prop", name: "Sac", descriptor: "a beige handbag", prompt: "A handbag", voice_id: "" } as const;
const beat = (key: string, ...ids: string[]) => ({
  key,
  summary: "s",
  voice_text: "v",
  duration_s: 4,
  continuity: "cut" as const,
  speaker: "",
  elements: ids.map((id) => ({ id, state: "" })),
});
const draft = (): DraftStory => ({ bible: "Anime", elements: [chloe, sac], beats: [beat("a", "chloe", "sac"), beat("b", "sac")] });

describe("storyOf", () => {
  it("lit le résultat de l'étape et donne une clé stable à chaque beat", () => {
    const story = storyOf({ bible: "Anime", elements: [chloe], beats: [{ summary: "s", voice_text: "v", duration_s: 4, elements: [] }] });
    expect(story.bible).toBe("Anime");
    expect(story.beats.map((b) => b.key)).toEqual(["beat-0"]);
  });
  it("tolère un résultat vide (projet existant) ou incomplet", () => {
    expect(storyOf({})).toEqual({ bible: "", elements: [], beats: [] });
    expect(storyOf(null).beats).toEqual([]);
    expect(storyOf({ beats: [{ summary: "s" }] }).beats[0]).toMatchObject({ voice_text: "", duration_s: 0, elements: [], continuity: "cut" });
  });
});

describe("toResult", () => {
  it("retire les clés des beats et garde les autres champs du résultat (avertissements)", () => {
    const result = toResult(draft(), { warnings: ["w"], extra: 1 });
    expect(result.beats).toEqual([
      { summary: "s", voice_text: "v", duration_s: 4, continuity: "cut", speaker: "", elements: [{ id: "chloe", state: "" }, { id: "sac", state: "" }] },
      { summary: "s", voice_text: "v", duration_s: 4, continuity: "cut", speaker: "", elements: [{ id: "sac", state: "" }] },
    ]);
    expect(result).toMatchObject({ bible: "Anime", elements: [chloe, sac], extra: 1 });
  });
});

describe("unknownIds", () => {
  it("liste les ids cités par un beat mais absents des éléments, sans doublon", () => {
    const story = { ...draft(), beats: [beat("a", "chloe", "fantome"), beat("b", "fantome", "autre")] };
    expect(unknownIds(story)).toEqual(["fantome", "autre"]);
    expect(unknownIds(draft())).toEqual([]);
  });
});

describe("withoutElement", () => {
  it("retire l'élément et ses mentions dans les beats", () => {
    const story = withoutElement(draft(), "sac");
    expect(story.elements.map((e) => e.id)).toEqual(["chloe"]);
    expect(story.beats.map((b) => b.elements.map((e) => e.id))).toEqual([["chloe"], []]);
  });
});

describe("newBeat / newElement / storyTotal", () => {
  it("crée un beat vide avec une clé unique", () => {
    expect(newBeat().key).not.toBe(newBeat().key);
    expect(newBeat()).toMatchObject({ summary: "", voice_text: "", elements: [], continuity: "cut" });
  });
  it("donne à un nouvel élément un id unique tiré de son nom", () => {
    expect(newElement("Le grand Sac!", [sac]).id).toBe("le_grand_sac");
    expect(newElement("Sac", [sac]).id).toBe("sac_2");
    expect(newElement("", []).id).toBe("element");
  });
  it("additionne les durées des beats", () => {
    expect(storyTotal(draft().beats)).toBe(8);
  });
});

describe("continuity", () => {
  it("lit la continuité d'un beat, « cut » pour une valeur absente ou inconnue, et jamais « continue » au premier beat", () => {
    const story = storyOf({
      beats: [
        { summary: "a", continuity: "continue" },
        { summary: "b", continuity: "continue" },
        { summary: "c", continuity: "nimporte" },
        { summary: "d" },
      ],
    });
    expect(story.beats.map((b) => b.continuity)).toEqual(["cut", "continue", "cut", "cut"]);
  });
  it("enregistre « continue » tel quel, sauf au premier beat (rien à poursuivre), même après un déplacement", () => {
    const story = draft();
    story.beats[1].continuity = "continue";
    expect(toResult(story, null).beats).toMatchObject([{ continuity: "cut" }, { continuity: "continue" }]);
    expect(toResult({ ...story, beats: [story.beats[1], story.beats[0]] }, null).beats).toMatchObject([
      { continuity: "cut" },
      { continuity: "cut" },
    ]);
  });
});

describe("speaker", () => {
  it("lit le locuteur d'un beat (vide : le narrateur) et la voix d'un élément", () => {
    const story = storyOf({
      elements: [{ id: "chloe", kind: "character", name: "Chloe", voice_id: "v1" }],
      beats: [{ summary: "a", speaker: "chloe" }, { summary: "b" }],
    });
    expect(story.beats.map((b) => b.speaker)).toEqual(["chloe", ""]);
    expect(story.elements[0].voice_id).toBe("v1");
    expect(storyOf({ elements: [{ id: "x", kind: "prop", name: "X" }] }).elements[0].voice_id).toBe("");
  });
  it("retirer un personnage vide le locuteur des beats qui le citaient", () => {
    const story = draft();
    story.beats[0].speaker = "chloe";
    expect(withoutElement(story, "chloe").beats[0].speaker).toBe("");
  });
  it("seuls les personnages peuvent parler", () => {
    expect(speakingElements(draft().elements).map((e) => e.id)).toEqual(["chloe"]);
  });
});

describe("blankBeat", () => {
  it("renvoie l'index du premier beat sans résumé ou sans voix off, -1 sinon", () => {
    expect(blankBeat(draft().beats)).toBe(-1);
    expect(blankBeat([beat("a"), { ...beat("b"), voice_text: "  " }])).toBe(1);
    expect(blankBeat([{ ...beat("a"), summary: "" }])).toBe(0);
  });
});

describe("elementCounts", () => {
  it("compte les éléments par type, au singulier ou au pluriel, sans les types absents", () => {
    expect(elementCounts([{ kind: "place" }, { kind: "character" }, { kind: "character" }])).toBe("2 personnages, 1 lieu");
    expect(elementCounts([{ kind: "prop" }])).toBe("1 accessoire");
    expect(elementCounts([])).toBe("");
  });
});
