import { describe, expect, it } from "vitest";
import type { PlanMessage } from "./api";
import { STEP_ORDER, type Step, type StepStatus } from "./steps";
import { chatBlockedReason, lastUndoable, needsPlanScreen, planLocks, planPhase, planProgress, storyNeedsApproval } from "./planChat";

/** Étapes de test : `story` approuvée sans résultat = projet existant (ancien chemin), sauf `written` (story écrite). */
const steps = (
  statuses: Partial<Record<Step["name"], StepStatus>>,
  written = false,
): Pick<Step, "name" | "status" | "result">[] => {
  const all = { story: written ? "pending" : "approved", ...statuses } as Partial<Record<Step["name"], StepStatus>>;
  return STEP_ORDER.map((name) => ({
    name,
    status: all[name] ?? "pending",
    result: name === "story" && written ? { beats: [{ summary: "s" }] } : {},
  }));
};

describe("needsPlanScreen", () => {
  it("est vrai tant que l'idée ou le script n'est pas validé", () => {
    expect(needsPlanScreen(steps({}))).toBe(true);
    expect(needsPlanScreen(steps({ idea: "awaiting_validation" }))).toBe(true);
    expect(needsPlanScreen(steps({ idea: "approved", script: "awaiting_validation" }))).toBe(true);
    expect(needsPlanScreen(steps({ idea: "approved", script: "failed" }))).toBe(true);
  });

  it("est vrai pendant l'histoire d'un nouveau projet", () => {
    expect(needsPlanScreen(steps({ idea: "approved", story: "awaiting_validation" }, true))).toBe(true);
  });

  it("est faux dès que le script est validé, et pour un projet terminé", () => {
    expect(needsPlanScreen(steps({ idea: "approved", script: "approved" }))).toBe(false);
    const done = Object.fromEntries(STEP_ORDER.map((n) => [n, "approved"])) as Record<Step["name"], StepStatus>;
    expect(needsPlanScreen(steps(done))).toBe(false);
  });
});

describe("planPhase", () => {
  it("génération en cours : l'idée ou le script tourne", () => {
    expect(planPhase(steps({ idea: "running" }), 0)).toBe("generating");
    expect(planPhase(steps({ idea: "approved", script: "running" }), 0)).toBe("generating");
  });

  it("échec : l'idée ou le script a échoué, jamais un écran vide", () => {
    expect(planPhase(steps({ idea: "failed" }), 0)).toBe("failed");
    expect(planPhase(steps({ idea: "approved", script: "failed" }), 4)).toBe("failed");
  });

  it("plan prêt : script à valider avec des scènes", () => {
    expect(planPhase(steps({ idea: "approved", script: "awaiting_validation" }), 4)).toBe("ready");
  });

  it("histoire en cours d'écriture : la story tourne", () => {
    expect(planPhase(steps({ idea: "approved", story: "running" }, true), 0)).toBe("generating");
    expect(planPhase(steps({ idea: "approved", story: "failed" }, true), 0)).toBe("failed");
  });

  it("histoire à relire : story écrite et scènes pas encore écrites (ou périmées)", () => {
    expect(planPhase(steps({ idea: "approved", story: "awaiting_validation" }, true), 0)).toBe("story");
    expect(planPhase(steps({ idea: "approved", story: "approved", script: "pending" }, true), 0)).toBe("story");
    expect(planPhase(steps({ idea: "approved", story: "awaiting_validation", script: "stale" }, true), 5)).toBe("story");
  });

  it("scènes écrites à partir d'une story : plan prêt", () => {
    expect(planPhase(steps({ idea: "approved", story: "approved", script: "awaiting_validation" }, true), 5)).toBe("ready");
  });

  it("projet existant (story validée et vide) : l'ancien parcours, sans phase histoire", () => {
    expect(planPhase(steps({ idea: "approved", script: "awaiting_validation" }), 4)).toBe("ready");
    expect(planPhase(steps({ idea: "approved" }), 0)).toBe("empty");
  });

  it("pas encore généré : projet ancien ou jamais lancé", () => {
    expect(planPhase(steps({}), 0)).toBe("empty");
    expect(planPhase(steps({ idea: "approved", script: "awaiting_validation" }), 0)).toBe("empty");
    expect(planPhase(steps({ idea: "approved", script: "stale" }), 3)).toBe("empty");
  });
});

describe("chatBlockedReason", () => {
  it("refuse avec des modifications non enregistrées", () => {
    expect(chatBlockedReason({ dirty: true, running: false })).toBe(
      "Enregistrez ou annulez vos modifications avant de parler à l'IA",
    );
  });

  it("refuse pendant une génération", () => {
    expect(chatBlockedReason({ dirty: false, running: true })).toContain("Une génération est en cours");
  });

  it("laisse parler sinon", () => {
    expect(chatBlockedReason({ dirty: false, running: false })).toBeNull();
  });
});

describe("lastUndoable", () => {
  const message = (id: number, can_undo: boolean): PlanMessage => ({
    id,
    role: "assistant",
    content: "",
    can_undo,
    created_at: "",
  });

  it("ne renvoie que le message annulable", () => {
    expect(lastUndoable([message(1, false), message(2, true), message(3, false)])?.id).toBe(2);
  });

  it("renvoie null quand rien ne s'annule", () => {
    expect(lastUndoable([message(1, false)])).toBeNull();
    expect(lastUndoable([])).toBeNull();
  });
});

describe("storyNeedsApproval", () => {
  it("valide l'histoire avant d'écrire les scènes, sauf si elle l'est déjà (l'API refuse approved → approved)", () => {
    expect(storyNeedsApproval(steps({ idea: "approved", story: "awaiting_validation" }, true))).toBe(true);
    expect(storyNeedsApproval(steps({ idea: "approved", story: "stale" }, true))).toBe(true);
    expect(storyNeedsApproval(steps({ idea: "approved", story: "approved", script: "stale" }, true))).toBe(false);
  });
});

describe("planLocks", () => {
  it("laisse la relecture libre pendant les images de référence, sauf l'enregistrement et le chat", () => {
    const locks = planLocks(steps({ script: "awaiting_validation", reference: "running" }, true), false);
    expect(locks.locked).toBe(false);
    expect(locks.running).toBe(true);
    expect(locks.saveBlocked).toMatch(/images du casting/);
  });
  it("gèle l'écran quand une autre étape tourne ou qu'une action est en cours", () => {
    expect(planLocks(steps({ script: "running" }, true), false).locked).toBe(true);
    expect(planLocks(steps({ script: "awaiting_validation" }, true), true).locked).toBe(true);
  });
  it("ne bloque rien quand rien ne tourne", () => {
    expect(planLocks(steps({ script: "awaiting_validation" }, true), false)).toEqual({
      locked: false,
      running: false,
      saveBlocked: null,
    });
  });
});

describe("planProgress", () => {
  const states = (s: Pick<Step, "name" | "status" | "result">[]) => planProgress(s).map((p) => `${p.label}:${p.state}`);

  it("suit l'idée, l'histoire puis les scènes, dans l'ordre", () => {
    expect(states(steps({ idea: "approved", story: "running" }, true))).toEqual(["Idée:done", "Histoire:running", "Scènes:todo"]);
  });

  it("une étape à valider est faite, une étape périmée à refaire, un échec est signalé", () => {
    expect(states(steps({ idea: "awaiting_validation", story: "failed", script: "stale" }, true))).toEqual([
      "Idée:done",
      "Histoire:failed",
      "Scènes:todo",
    ]);
  });

  it("rien de lancé : tout est à venir", () => {
    expect(states(steps({ story: "pending" }))).toEqual(["Idée:todo", "Histoire:todo", "Scènes:todo"]);
  });
});
