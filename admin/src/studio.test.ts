import { describe, expect, it } from "vitest";
import type { Asset, ProjectDetail, Scene } from "./api";
import { STEP_ORDER, type Step, type StepStatus } from "./steps";
import {
  activities,
  busyReason,
  autopilotLabel,
  importedTitle,
  laneState,
  neighbourScene,
  queueLabel,
  completionMessage,
  exportBlockedReason,
  generationTiming,
  renderIsCurrent,
  reorderedIds,
  rulerTicks,
  sceneAt,
  shortcutFor,
  shortText,
  stableUrls,
  timeline,
  toolOf,
  toolState,
  toolStep,
  TOOLS,
} from "./studio";

const steps = (statuses: Partial<Record<Step["name"], StepStatus>>) =>
  STEP_ORDER.map((name) => ({ name, status: statuses[name] ?? "pending" }));
const tool = (id: string) => TOOLS.find((t) => t.id === id)!;

describe("toolOf / toolStep", () => {
  it("range la référence dans Clips et le rendu final dans Export", () => {
    expect(toolOf("reference").id).toBe("clips");
    expect(toolOf("clips").id).toBe("clips");
    expect(toolOf("final").id).toBe("export");
  });
  it("ouvre l'étape courante si l'outil la contient, sinon son étape principale", () => {
    expect(toolStep(tool("clips"), "reference")).toBe("reference");
    expect(toolStep(tool("clips"), "voice")).toBe("clips");
    expect(toolStep(tool("idea"), "voice")).toBe("idea");
  });
});

describe("toolState", () => {
  it("suit le statut de l'étape", () => {
    expect(toolState(tool("idea"), steps({ idea: "approved" }))).toBe("approved");
    expect(toolState(tool("script"), steps({ script: "awaiting_validation" }))).toBe("awaiting");
    expect(toolState(tool("script"), steps({ script: "stale" }))).toBe("awaiting");
    expect(toolState(tool("voice"), steps({ voice: "failed" }))).toBe("failed");
    expect(toolState(tool("music"), steps({}))).toBe("todo");
  });
  it("ignore la référence facultative non lancée ou ignorée", () => {
    expect(toolState(tool("clips"), steps({ reference: "pending", clips: "approved" }))).toBe("approved");
    expect(toolState(tool("clips"), steps({ reference: "approved", clips: "pending" }))).toBe("todo");
  });
  it("donne la priorité à la génération en cours puis à l'échec", () => {
    expect(toolState(tool("clips"), steps({ reference: "running", clips: "failed" }))).toBe("running");
    expect(toolState(tool("clips"), steps({ reference: "failed", clips: "awaiting_validation" }))).toBe("failed");
  });
});

describe("timeline", () => {
  it("donne à chaque scène une largeur proportionnelle à sa durée", () => {
    const { blocks, total } = timeline([{ duration_s: 3 }, { duration_s: 6 }, { duration_s: 3 }]);
    expect(total).toBe(12);
    expect(blocks.map((b) => [b.start, b.left, b.width])).toEqual([
      [0, 0, 25],
      [3, 25, 50],
      [9, 75, 25],
    ]);
  });
  it("supporte un script vide", () => {
    expect(timeline([])).toEqual({ blocks: [], total: 0 });
  });
});

describe("sceneAt", () => {
  const { blocks } = timeline([{ duration_s: 3 }, { duration_s: 3 }]);
  it("trouve la scène jouée", () => {
    expect(sceneAt(blocks, 0)).toBe(0);
    expect(sceneAt(blocks, 2.9)).toBe(0);
    expect(sceneAt(blocks, 3)).toBe(1);
  });
  it("tolère l'arrondi d'un placement en début de scène", () => {
    expect(sceneAt(blocks, 2.99999)).toBe(1);
  });
  it("reste sur la dernière scène en fin de vidéo, -1 sans scène", () => {
    expect(sceneAt(blocks, 99)).toBe(1);
    expect(sceneAt([], 1)).toBe(-1);
  });
});

describe("rulerTicks", () => {
  it("ne libelle pas la graduation de bout de règle", () => {
    expect(rulerTicks(30).filter((t) => t.label).map((t) => t.t)).toEqual([0, 5, 10, 15, 20, 25]);
  });
  it("gradue chaque seconde, libellé toutes les 5 s", () => {
    const ticks = rulerTicks(12);
    expect(ticks).toHaveLength(13);
    expect(ticks.filter((t) => t.label).map((t) => t.t)).toEqual([0, 5, 10]);
  });
  it("espace les graduations au-delà d'une minute", () => {
    const ticks = rulerTicks(90);
    expect(ticks.map((t) => t.t).slice(0, 3)).toEqual([0, 5, 10]);
    expect(ticks.filter((t) => t.label).map((t) => t.t)).toEqual([0, 10, 20, 30, 40, 50, 60, 70, 80]);
  });
});

describe("neighbourScene / laneState / shortText", () => {
  it("borne la scène voisine", () => {
    expect(neighbourScene(0, -1, 10)).toBe(0);
    expect(neighbourScene(9, 1, 10)).toBe(9);
    expect(neighbourScene(4, 1, 10)).toBe(5);
    expect(neighbourScene(0, 1, 0)).toBe(0);
  });
  it("distingue média prêt, en génération et vide", () => {
    expect(laneState(true, true)).toBe("ready");
    expect(laneState(false, true)).toBe("generating");
    expect(laneState(false, false)).toBe("empty");
  });
  it("coupe un texte aux premiers mots", () => {
    expect(shortText("Elle a trois cœurs qui battent")).toBe("Elle a trois cœurs…");
    expect(shortText("  Danger  ? ")).toBe("Danger ?");
  });
});

describe("autopilotLabel", () => {
  const scene = (id: number) => ({ id }) as Scene;
  const asset = (kind: Asset["kind"], scene_id: number) => ({ kind, scene_id }) as Asset;
  const project = (statuses: Partial<Record<Step["name"], StepStatus>>, assets: Asset[] = []) =>
    ({ steps: steps(statuses), scenes: [scene(1), scene(2), scene(3)], assets }) as unknown as ProjectDetail;

  it("compte les scènes qui ont un clip pendant l'étape Clips", () => {
    const p = project({ idea: "approved", story: "approved", script: "approved", clips: "running" }, [
      asset("clip", 1),
      asset("clip", 1),
      asset("clip", 2),
      asset("voice", 3),
    ]);
    expect(autopilotLabel(p)).toBe("Clips 2/3");
  });
  it("nomme l'étape en cours, sinon l'étape à venir", () => {
    expect(autopilotLabel(project({ idea: "running" }))).toBe("Idée");
    expect(autopilotLabel(project({ idea: "approved", story: "approved", script: "approved", clips: "approved", voice: "approved", music: "approved" }))).toBe("Montage");
  });
});

describe("shortcutFor", () => {
  it("espace lance la lecture hors des contrôles", () => {
    expect(shortcutFor(" ", { tag: "BODY" })).toBe("toggle");
    expect(shortcutFor(" ", { tag: "BUTTON", scene: true })).toBe("toggle");
    expect(shortcutFor(" ", { tag: "BUTTON" })).toBeNull();
  });
  it("flèches : scène voisine, sauf dans un champ ou un groupe radio", () => {
    expect(shortcutFor("ArrowLeft", { tag: "DIV" })).toBe("prev");
    expect(shortcutFor("ArrowRight", { tag: "BUTTON" })).toBe("next");
    expect(shortcutFor("ArrowRight", { tag: "TEXTAREA" })).toBeNull();
    expect(shortcutFor("ArrowRight", { tag: "INPUT", role: "radio" })).toBeNull();
    expect(shortcutFor("ArrowRight", { tag: "VIDEO" })).toBeNull();
    expect(shortcutFor("a", { tag: "BODY" })).toBeNull();
  });
});

describe("stableUrls", () => {
  const signed = (time: string) => `http://s3/clip.mp4?X-Amz-Date=20261018T${time}Z&X-Amz-Signature=${time}`;
  const asset = (id: number, url: string) => ({ id, url }) as Asset;
  it("garde l'URL déjà vue d'un asset tant qu'elle a moins de 30 min, puis prend la nouvelle", () => {
    const cache = new Map();
    stableUrls(cache, [asset(1, signed("110000"))]);
    expect(stableUrls(cache, [asset(1, signed("112000")), asset(2, signed("112000"))]).map((a) => a.url)).toEqual([
      signed("110000"),
      signed("112000"),
    ]);
    expect(stableUrls(cache, [asset(1, signed("113100"))])[0].url).toBe(signed("113100"));
  });
  it("garde l'URL d'un asset non signé", () => {
    const cache = new Map();
    stableUrls(cache, [asset(1, "a1")]);
    expect(stableUrls(cache, [asset(1, "a2")])[0].url).toBe("a1");
  });
});

describe("renderIsCurrent", () => {
  const withMontage = (montage: string) => [{ name: "clips", status: "approved" }, { name: "montage", status: montage }] as never;
  it("accepte le rendu d'un montage produit", () => {
    expect(renderIsCurrent(withMontage("approved"))).toBe(true);
    expect(renderIsCurrent(withMontage("awaiting_validation"))).toBe(true);
  });
  it("le refuse quand le montage est périmé, relancé, en échec ou pas fait", () => {
    for (const status of ["stale", "running", "failed", "pending"]) expect(renderIsCurrent(withMontage(status))).toBe(false);
  });
});

describe("reorderedIds", () => {
  it("échange la scène avec sa voisine", () => {
    expect(reorderedIds([10, 20, 30], 1, -1)).toEqual([20, 10, 30]);
    expect(reorderedIds([10, 20, 30], 1, 1)).toEqual([10, 30, 20]);
  });
  it("ne bouge pas une scène déjà au bord, et ne modifie pas la liste d'origine", () => {
    const ids = [10, 20, 30];
    expect(reorderedIds(ids, 0, -1)).toBeNull();
    expect(reorderedIds(ids, 2, 1)).toBeNull();
    reorderedIds(ids, 0, 1);
    expect(ids).toEqual([10, 20, 30]);
  });
});

describe("completionMessage", () => {
  const steps = (status: string, error: string | null = null) => [{ name: "clips", status, error }] as never;
  it("annonce une étape qui vient de finir", () => {
    expect(completionMessage(steps("running"), steps("awaiting_validation"))).toBe("Clips : à valider");
    expect(completionMessage(steps("running"), steps("approved"))).toBe("Clips : terminée");
  });
  it("distingue l'échec de l'arrêt volontaire", () => {
    expect(completionMessage(steps("running"), steps("failed", "boom"))).toBe("Clips : échec");
    expect(completionMessage(steps("running"), steps("failed", "Arrêtée par l'utilisateur"))).toBe("Clips : arrêtée");
  });
  it("se tait sans transition depuis « en cours »", () => {
    expect(completionMessage(undefined, steps("awaiting_validation"))).toBeNull();
    expect(completionMessage(steps("pending"), steps("running"))).toBeNull();
    expect(completionMessage(steps("running"), steps("running"))).toBeNull();
  });
});

describe("exportBlockedReason", () => {
  const withMontage = (montage: string) => [{ name: "montage", status: montage }] as never;
  it("autorise l'export d'un rendu à jour", () => {
    expect(exportBlockedReason(withMontage("approved"), true)).toBeNull();
  });
  it("refuse un rendu périmé en disant quoi faire", () => {
    expect(exportBlockedReason(withMontage("stale"), true)).toMatch(/relancez le montage/);
  });
  it("refuse tant que rien n'est monté", () => {
    expect(exportBlockedReason(withMontage("pending"), false)).toBe("Disponible après le montage");
  });
});

describe("importedTitle", () => {
  it("affiche le nom d'origine d'une variante importée, rien sans nom", () => {
    expect(importedTitle({ original_name: "plage été.mp4" })).toBe("Importée : plage été.mp4");
    expect(importedTitle({ original_name: null })).toBeUndefined();
  });
});

describe("activities", () => {
  const scenes = [{ id: 11, position: 1 }, { id: 12, position: 2 }];
  const step = (name: Step["name"], extra: Partial<Step> = {}): Step => ({
    name, status: "running", params: {}, result: null, error: null, ...extra,
  });

  it("ne liste que les étapes en cours et dit laquelle, avec quelle scène ou quel avancement", () => {
    const list = activities(
      [step("script", { status: "approved" }), step("clips", { target_scene: 12 }), step("voice", { progress: { done: 1, total: 2 } }), step("music")],
      scenes,
    );
    expect(list).toMatchObject([
      { step: "clips", label: "Clips", detail: "scène 2", sceneId: 12 },
      { step: "voice", label: "Voix off", detail: "1 scène sur 2", sceneId: null },
      { step: "music", label: "Musique", detail: "en cours", sceneId: null },
    ]);
  });

  it("est vide quand rien ne tourne", () => {
    expect(activities([step("clips", { status: "awaiting_validation" })], scenes)).toEqual([]);
  });
});

describe("generationTiming", () => {
  const since = "2026-10-23T10:00:00Z";
  const at = (s: number) => Date.parse(since) + s * 1000;
  it("ne dit rien sans date de lancement", () => {
    expect(generationTiming({}, at(10), 60)).toBeNull();
  });
  it("estime d'après le modèle tant qu'aucune scène n'est prête", () => {
    expect(generationTiming({ running_since: since }, at(100), 300)).toEqual({ elapsed: 100, remaining: 200 });
    expect(generationTiming({ running_since: since, progress: { done: 0, total: 4 } }, at(100), 300)).toEqual({ elapsed: 100, remaining: 1100 });
  });
  it("passe au rythme mesuré dès qu'une scène est prête", () => {
    expect(generationTiming({ running_since: since, progress: { done: 2, total: 4 } }, at(200), 999)).toEqual({ elapsed: 200, remaining: 200 });
  });
  it("ne promet rien sans estimation, et plafonne à zéro quand c'est plus long que prévu", () => {
    expect(generationTiming({ running_since: since }, at(50), null)).toEqual({ elapsed: 50, remaining: null });
    expect(generationTiming({ running_since: since }, at(400), 300)?.remaining).toBe(0);
  });
});

describe("busyReason", () => {
  it("dit ce qui tourne, sinon l'action en attente, sinon rien", () => {
    expect(busyReason([{ step: "clips", source: { name: "clips", status: "running", params: {}, result: null, error: null }, label: "Clips", detail: "scène 6", sceneId: 1 }], false)).toBe("En cours : Clips, scène 6");
    expect(busyReason([], true)).toBe("Action en cours");
    expect(busyReason([], false)).toBeNull();
  });
});

describe("queueLabel", () => {
  const scenes = [{ id: 11, position: 7 }];
  it("nomme l'étape et la scène visée", () => {
    expect(queueLabel({ id: 1, step: "clips", scene_id: 11 }, scenes)).toBe("Clips, scène 7");
  });
  it("sans scène (ou scène disparue), seulement l'étape", () => {
    expect(queueLabel({ id: 2, step: "voice", scene_id: null }, scenes)).toBe("Voix off");
    expect(queueLabel({ id: 3, step: "clips", scene_id: 99 }, scenes)).toBe("Clips");
  });
});
