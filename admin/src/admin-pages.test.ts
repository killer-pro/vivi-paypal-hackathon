import { describe, expect, it } from "vitest";
import { breakdown, formatShare } from "./costs";
import { clock } from "./format";
import { parseVoices, settingsBody, voiceLabel, withCurrent, type Settings } from "./settings";

describe("clock", () => {
  it("formate en m:ss", () => {
    expect(clock(3.02)).toBe("0:03");
    expect(clock(125)).toBe("2:05");
    expect(clock(59.6)).toBe("1:00");
  });
});

describe("settingsBody", () => {
  const saved: Settings = {
    anthropic_api_key: "••••abcd",
    fal_key: "",
    comfyui_url: "http://comfy:8188",
    default_voice_id: "v1",
  };
  const draftOf = (patch: Partial<Settings>): Settings => ({
    ...saved,
    anthropic_api_key: "",
    fal_key: "",
    ...patch,
  });

  it("n'envoie rien sans modification", () => {
    expect(settingsBody(saved, draftOf({}))).toEqual({});
  });
  it("n'envoie que les champs modifiés", () => {
    expect(settingsBody(saved, draftOf({ default_voice_id: "v2" }))).toEqual({ default_voice_id: "v2" });
  });
  it("envoie un secret saisi", () => {
    expect(settingsBody(saved, draftOf({ fal_key: "  fal-123  " }))).toEqual({ fal_key: "fal-123" });
  });
  it("ne renvoie jamais un secret masqué ni un secret vide", () => {
    expect(settingsBody(saved, draftOf({ anthropic_api_key: "••••abcd" }))).toEqual({});
    expect(settingsBody(saved, draftOf({ anthropic_api_key: "   " }))).toEqual({});
  });
  it("permet de vider un champ non secret", () => {
    expect(settingsBody(saved, draftOf({ comfyui_url: "" }))).toEqual({ comfyui_url: "" });
  });
  it("traite la clé Gemini comme un secret", () => {
    expect(settingsBody(saved, draftOf({ gemini_api_key: "••••wxyz" }))).toEqual({});
    expect(settingsBody(saved, draftOf({ gemini_api_key: " AIza-1 ", llm_provider: "gemini" }))).toEqual({
      gemini_api_key: "AIza-1",
      llm_provider: "gemini",
    });
  });
});

describe("withCurrent", () => {
  it("garde la valeur enregistrée absente de la liste, en tête", () => {
    expect(withCurrent(["a", "b"], "a")).toEqual(["a", "b"]);
    expect(withCurrent(["a", "b"], "custom")).toEqual(["custom", "a", "b"]);
    expect(withCurrent(["a"], "")).toEqual(["a"]);
  });
});

describe("breakdown", () => {
  it("trie par montant décroissant, part du total et largeur relative au maximum", () => {
    expect(breakdown({ a: 1, b: 3, c: 0 }, (k) => k.toUpperCase())).toEqual([
      { key: "b", label: "B", usd: 3, share: 0.75, ratio: 1 },
      { key: "a", label: "A", usd: 1, share: 0.25, ratio: 1 / 3 },
      { key: "c", label: "C", usd: 0, share: 0, ratio: 0 },
    ]);
  });
  it("total nul : parts et largeurs à zéro", () => {
    expect(breakdown({ a: 0 }, (k) => k)).toEqual([{ key: "a", label: "a", usd: 0, share: 0, ratio: 0 }]);
  });
});

describe("formatShare", () => {
  // espaces insécables normalisées : leur variante (U+00A0 ou U+202F) dépend de la version d'ICU
  const share = (x: number) => formatShare(x).replace(/\s/g, " ");
  it("arrondit au pourcent, sans afficher 0 % pour un poste non nul", () => {
    expect(share(0.98)).toBe("98 %");
    expect(share(0.001)).toBe("< 1 %");
    expect(share(0)).toBe("0 %");
  });
});

describe("catalogue de voix", () => {
  const voices = [{ id: "v1", name: "Camille" }];
  it("lit le réglage JSON, vide s'il est absent ou illisible", () => {
    expect(parseVoices(JSON.stringify(voices))).toEqual(voices);
    expect(parseVoices(undefined)).toEqual([]);
    expect(parseVoices("pas du json")).toEqual([]);
    expect(parseVoices('{"id": "v1"}')).toEqual([]);
  });
  it("nomme une voix, ou garde son identifiant si elle n'est plus au catalogue", () => {
    expect(voiceLabel(voices, "v1")).toBe("Camille");
    expect(voiceLabel(voices, "v9")).toBe("v9");
  });
});
