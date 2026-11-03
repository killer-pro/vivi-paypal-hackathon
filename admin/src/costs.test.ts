import { describe, expect, it } from "vitest";
import { budgetState, costStepLabel } from "./costs";

describe("budgetState", () => {
  it("n'alerte qu'à l'approche du plafond, jamais sans plafond", () => {
    expect(budgetState(50, 0)).toBe("none");
    expect(budgetState(1, 10)).toBe("ok");
    expect(budgetState(8, 10)).toBe("near");
    expect(budgetState(10, 10)).toBe("over");
  });
});

describe("costStepLabel", () => {
  it("nomme les étapes et l'assistant IA", () => {
    expect(costStepLabel("clips")).toBe("Clips");
    expect(costStepLabel("assist")).toBe("Assistant IA");
    expect(costStepLabel("inconnue")).toBe("inconnue");
  });
});
