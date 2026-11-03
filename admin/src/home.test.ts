import { describe, expect, it } from "vitest";
import { cardState, isFiltered, libraryPath, progress } from "./home";

describe("progress", () => {
  it("marque les étapes validées, la courante et la suite", () => {
    expect(progress("clips")).toEqual(["done", "done", "done", "done", "current", "todo", "todo", "todo", "todo"]);
  });
  it("tout est validé quand il n'y a plus d'étape courante", () => {
    expect(progress(null)).toEqual(Array(9).fill("done"));
  });
});

describe("cardState", () => {
  const base = { status: "draft", autopilot: false, current_step: "idea" as const, current_status: "pending" as const };
  it("vidéo terminée", () => {
    expect(cardState({ ...base, status: "done", current_step: null, current_status: null })).toEqual({
      tone: "approved",
      label: "Terminée",
    });
  });
  it("génération automatique en cours", () => {
    expect(cardState({ ...base, autopilot: true, current_step: "clips", current_status: "running" })).toEqual({
      tone: "running",
      label: "En génération…",
      live: true,
    });
  });
  it("un échec l'emporte et nomme l'étape", () => {
    expect(cardState({ ...base, current_step: "voice", current_status: "failed" })).toEqual({
      tone: "failed",
      label: "Échec : Voix off",
    });
  });
  it("pas à pas : statut de l'étape courante", () => {
    expect(cardState({ ...base, current_step: "script", current_status: "awaiting_validation" })).toEqual({
      tone: "awaiting_validation",
      label: "À valider : Script et scènes",
    });
    expect(cardState({ ...base, current_step: "music", current_status: "running" })).toEqual({
      tone: "running",
      label: "En cours : Musique",
    });
    expect(cardState(base)).toEqual({ tone: "pending", label: "À lancer : Idée" });
  });
});

describe("libraryPath", () => {
  const base = { search: "", sort: "recent", status: "", limit: 24 } as const;
  it("omet la recherche vide et le filtre « Toutes »", () => {
    expect(libraryPath(base)).toBe("/projects?sort=recent&limit=24");
  });
  it("encode la recherche (espaces ôtés aux bords) et le filtre", () => {
    expect(libraryPath({ ...base, search: "  café & lait ", status: "done", sort: "cost", limit: 48 })).toBe(
      "/projects?sort=cost&limit=48&q=caf%C3%A9+%26+lait&status=done",
    );
  });
});

describe("isFiltered", () => {
  it("ne compte ni le tri ni une recherche faite d'espaces", () => {
    expect(isFiltered({ search: "   ", status: "" })).toBe(false);
    expect(isFiltered({ search: "a", status: "" })).toBe(true);
    expect(isFiltered({ search: "", status: "draft" })).toBe(true);
  });
});
