import { describe, expect, it } from "vitest";
import { assistBlocked, assistBody, assistStepLabel, canUndo, patchByKey, replyIsStale } from "./assist";

describe("assistBody", () => {
  it("omet la consigne vide et le contexte absent", () => {
    expect(assistBody("angle", "generate", "", "   ")).toEqual({ field_kind: "angle", mode: "generate", text: "" });
  });
  it("transmet consigne nettoyée, projet, scène et durée du brouillon", () => {
    expect(
      assistBody("voice_text", "rewrite", "Tu dors mal ?", " plus court ", { projectId: 3, sceneId: 9, durationS: 4 }),
    ).toEqual({
      field_kind: "voice_text",
      mode: "rewrite",
      text: "Tu dors mal ?",
      instruction: "plus court",
      project_id: 3,
      scene_id: 9,
      duration_s: 4,
    });
  });
  it("ignore une scène sans projet et une durée invalide (champ vidé : NaN)", () => {
    expect(assistBody("voice_text", "generate", "", "", { sceneId: 9, durationS: Number.NaN })).toEqual({
      field_kind: "voice_text",
      mode: "generate",
      text: "",
    });
  });
});

describe("assistBlocked", () => {
  it("bloque Reformuler sans texte, pas Générer", () => {
    expect(assistBlocked("rewrite", "  ", false, false)).toMatch(/texte à reformuler/);
    expect(assistBlocked("generate", "", false, false)).toBeNull();
  });
  it("bloque pendant le chargement et quand l'étape est verrouillée", () => {
    expect(assistBlocked("generate", "x", false, true)).toMatch(/en cours/);
    expect(assistBlocked("rewrite", "x", true, false)).toMatch(/génération/);
  });
});

describe("canUndo", () => {
  it("tant que le champ contient la proposition", () => {
    expect(canUndo("abc", { result: "abc" })).toBe(true);
    expect(canUndo("abc modifié", { result: "abc" })).toBe(false);
    expect(canUndo("abc", null)).toBe(false);
  });
});

describe("assistStepLabel", () => {
  it("nomme les appels de l'assistant dans le journal des coûts", () => {
    expect(assistStepLabel("assist:voice_text")).toBe("Assistant IA (voix off)");
    expect(assistStepLabel("assist:inconnu")).toBeNull();
    expect(assistStepLabel("script")).toBeNull();
  });
});

describe("replyIsStale", () => {
  it("ignore une réponse si le champ a changé depuis la demande", () => {
    expect(replyIsStale("avant", "avant")).toBe(false);
    expect(replyIsStale("avant", "avant, modifié")).toBe(true);
  });
});

describe("patchByKey", () => {
  it("modifie l'élément par sa clé, même si la liste a été réordonnée entre-temps", () => {
    const list = [
      { key: "b", voice_text: "B" },
      { key: "a", voice_text: "A" },
    ];
    expect(patchByKey(list, "a", { voice_text: "A2" })).toEqual([
      { key: "b", voice_text: "B" },
      { key: "a", voice_text: "A2" },
    ]);
    expect(patchByKey(list, "absente", { voice_text: "x" })).toEqual(list); // scène supprimée : rien n'est écrit
  });
});
