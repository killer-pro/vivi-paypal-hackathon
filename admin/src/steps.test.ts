import { describe, expect, it } from "vitest";
import { affectedDownstream, currentStep, dependents, missingScenes, previousApproved, resumeInfo, runningDownstream, type Step } from "./steps";

const s = (name: string, status: string) => ({ name, status }) as Step;

describe("currentStep", () => {
  it("renvoie la première étape non validée", () => {
    expect(currentStep([s("idea", "approved"), s("story", "approved"), s("script", "awaiting_validation"), s("reference", "pending")])).toBe("script");
  });
  it("passe par l'histoire avant le script", () => {
    expect(currentStep([s("idea", "approved"), s("story", "awaiting_validation"), s("script", "pending")])).toBe("story");
  });
  it("ignore l'étape optionnelle reference si en pending", () => {
    expect(currentStep([s("idea", "approved"), s("story", "approved"), s("script", "approved"), s("reference", "pending"), s("clips", "pending")])).toBe("clips");
  });
  it("renvoie final quand tout est validé", () => {
    expect(currentStep(["idea","story","script","reference","clips","voice","music","montage","final"].map(n => s(n, "approved")))).toBe("final");
  });
});

describe("runningDownstream", () => {
  it("liste les étapes en aval qui tournent", () => {
    const steps = [s("idea", "approved"), s("script", "approved"), s("clips", "running"), s("montage", "running")];
    expect(runningDownstream(steps, "script")).toEqual(["clips", "montage"]);
    expect(runningDownstream([s("story", "approved"), s("script", "running")], "story")).toEqual(["script"]);
    expect(runningDownstream(steps, "clips")).toEqual(["montage"]);
  });
  it("ignore l'étape elle-même et l'amont", () => {
    expect(runningDownstream([s("idea", "running"), s("script", "running")], "script")).toEqual([]);
  });
});

describe("indépendance de la voix et de la musique", () => {
  it("la voix ne dépend pas des clips, le montage dépend des trois", () => {
    const steps = [s("idea", "approved"), s("story", "approved"), s("script", "approved"), s("clips", "running"), s("voice", "pending")];
    expect(previousApproved(steps, "voice")).toBe(true);
    expect(previousApproved([s("idea", "approved"), s("story", "awaiting_validation")], "script")).toBe(false);
    expect(previousApproved(steps, "montage")).toBe(false);
    expect(dependents("clips")).toEqual(["montage", "final"]);
    expect(dependents("voice")).toEqual(["montage", "final"]);
  });
  it("une régénération de clips ne bloque pas la voix en cours", () => {
    expect(runningDownstream([s("clips", "approved"), s("voice", "running")], "clips")).toEqual([]);
  });
});

describe("resumeInfo", () => {
  it("compte les scènes restantes et accorde la phrase", () => {
    expect(resumeInfo({ done: 3, total: 10 })).toEqual({ remaining: 7, text: "3 scènes sur 10 déjà générées" });
    expect(resumeInfo({ done: 1, total: 4 })).toEqual({ remaining: 3, text: "1 scène sur 4 déjà générée" });
  });
  it("ne descend jamais sous zéro (scènes supprimées depuis)", () => {
    expect(resumeInfo({ done: 5, total: 4 }).remaining).toBe(0);
  });
});

describe("missingScenes", () => {
  const scenes = [{ id: 1 }, { id: 2 }, { id: 3 }];
  const assets = [
    { scene_id: 1, kind: "clip" },
    { scene_id: 1, kind: "voice" },
    { scene_id: 2, kind: "voice" },
    { scene_id: null, kind: "render" },
  ] as const;
  it("liste les scènes sans média du type demandé", () => {
    expect(missingScenes(scenes, [...assets], "clip").map((x) => x.id)).toEqual([2, 3]);
    expect(missingScenes(scenes, [...assets], "voice").map((x) => x.id)).toEqual([3]);
  });
  it("tout est manquant sans asset", () => {
    expect(missingScenes(scenes, [], "clip")).toHaveLength(3);
  });
});

describe("affectedDownstream", () => {
  const done = { result: { ok: true } };
  const empty = { result: {} };

  it("ne retient que les étapes en aval qui ont déjà un résultat", () => {
    const steps = [
      { name: "clips", ...done },
      { name: "voice", ...done },
      { name: "montage", ...done },
      { name: "final", ...empty },
    ] as const;
    expect(affectedDownstream([...steps], "clips")).toEqual(["montage"]);
  });

  it("ne compte pas la voix quand on relance les clips (indépendants)", () => {
    expect(affectedDownstream([{ name: "voice", ...done }], "clips")).toEqual([]);
  });
});
