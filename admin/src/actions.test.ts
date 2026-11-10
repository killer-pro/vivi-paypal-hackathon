import { describe, expect, it } from "vitest";
import { ApiError, errorMessage } from "./api";
import { availableActions, hasResult, previousApproved, statusLabel, type Step, type StepStatus } from "./steps";

const step = (status: StepStatus, name: Step["name"] = "clips"): Step => ({
  name,
  status,
  params: {},
  result: null,
  error: null,
});

describe("availableActions", () => {
  it("running : aucune action active", () => {
    expect(availableActions(step("running"), true)).toEqual({
      canRun: false,
      canApprove: false,
      showRetry: false,
      stale: false,
    });
  });
  it("failed : propose de relancer", () => {
    expect(availableActions(step("failed"), true)).toMatchObject({ showRetry: true, canApprove: false });
  });
  it("awaiting_validation : validation possible", () => {
    expect(availableActions(step("awaiting_validation"), true)).toMatchObject({
      canApprove: true,
      canRun: true,
      showRetry: false,
    });
  });
  it("pending sans étape précédente validée : génération impossible", () => {
    expect(availableActions(step("pending"), false)).toEqual({
      canRun: false,
      canApprove: false,
      showRetry: false,
      stale: false,
    });
  });
  it("pending avec étapes précédentes validées : génération possible", () => {
    expect(availableActions(step("pending"), true)).toMatchObject({ canRun: true, canApprove: false });
  });
  it("stale : signalée et régénérable", () => {
    expect(availableActions(step("stale"), true)).toMatchObject({ stale: true, canRun: true });
  });
  it("stale avec une étape précédente non validée : ni génération ni validation", () => {
    expect(availableActions(step("stale"), false)).toEqual({
      canRun: false,
      canApprove: false,
      showRetry: false,
      stale: true,
    });
  });
  it("montage périmé : à relancer, jamais validé tel quel (ce serait l'ancienne vidéo)", () => {
    expect(availableActions(step("stale", "montage"), true)).toMatchObject({ stale: true, canRun: true, canApprove: false });
  });
  it("approved : régénérable, pas de nouvelle validation", () => {
    expect(availableActions(step("approved"), true)).toMatchObject({ canRun: true, canApprove: false });
  });
});

describe("previousApproved", () => {
  const all = (status: StepStatus) =>
    (["idea", "script", "reference", "clips"] as const).map((name) => step(status, name));

  it("vrai pour la première étape", () => {
    expect(previousApproved(all("pending"), "idea")).toBe(true);
  });
  it("ignore l'étape optionnelle reference", () => {
    const steps = all("approved").map((s) => (s.name === "reference" ? { ...s, status: "pending" as const } : s));
    expect(previousApproved(steps, "clips")).toBe(true);
  });
  it("faux si une étape obligatoire précédente n'est pas validée", () => {
    const steps = all("approved").map((s) => (s.name === "script" ? { ...s, status: "stale" as const } : s));
    expect(previousApproved(steps, "clips")).toBe(false);
  });
});

describe("hasResult", () => {
  it("faux pour un résultat vide (étape jamais générée) ou absent", () => {
    expect(hasResult({ result: {} })).toBe(false);
    expect(hasResult({ result: null })).toBe(false);
  });
  it("vrai dès qu'un résultat existe", () => {
    expect(hasResult({ result: { angle: "x" } })).toBe(true);
  });
});

describe("statusLabel", () => {
  it("référence en attente : facultative ; validée sans résultat : ignorée", () => {
    expect(statusLabel({ ...step("pending", "reference"), result: {} })).toBe("Facultative");
    expect(statusLabel({ ...step("approved", "reference"), result: {} })).toBe("Ignorée");
    expect(statusLabel({ ...step("approved", "reference"), result: { asset_id: 1 } })).toBe("Validée");
  });
  it("autres étapes : libellé du statut", () => {
    expect(statusLabel(step("stale"))).toBe("Périmée");
  });
});

describe("errorMessage", () => {
  it("affiche le detail de l'API, même en 5xx (ex. file d'attente indisponible)", () => {
    expect(errorMessage(new ApiError(409, "Génération en cours (clips)", true))).toBe("Génération en cours (clips)");
    expect(errorMessage(new ApiError(503, "File d'attente indisponible", true))).toBe("File d'attente indisponible");
  });
  it("sans réponse JSON de l'API (proxy, réseau) : serveur injoignable", () => {
    expect(errorMessage(new ApiError(502, "Bad Gateway"))).toBe("Serveur injoignable");
    expect(errorMessage(new TypeError("fetch failed"))).toBe("Serveur injoignable");
  });
});
