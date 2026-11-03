import { describe, expect, it } from "vitest";
import { MAX_THEME } from "./limits";
import { cleanIdea, forgetIdea, pendingIdea, rememberIdea } from "./pendingIdea";

const fakeStore = () => {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
};

describe("cleanIdea", () => {
  it("retire les espaces autour et refuse le vide", () => {
    expect(cleanIdea("  une pub sneaker \n")).toBe("une pub sneaker");
    expect(cleanIdea("   ")).toBeNull();
  });

  it("coupe à la limite du champ idée", () => {
    expect(cleanIdea("a".repeat(MAX_THEME + 10))).toHaveLength(MAX_THEME);
  });
});

describe("idée mémorisée", () => {
  it("se relit sans s'effacer, puis s'oublie", () => {
    const store = fakeStore();
    rememberIdea(" 3 astuces pour dormir ", store);
    expect(pendingIdea(store)).toBe("3 astuces pour dormir");
    expect(pendingIdea(store)).toBe("3 astuces pour dormir");
    forgetIdea(store);
    expect(pendingIdea(store)).toBeNull();
  });

  it("n'écrase pas l'idée précédente par une saisie vide", () => {
    const store = fakeStore();
    rememberIdea("première", store);
    rememberIdea("  ", store);
    expect(pendingIdea(store)).toBe("première");
  });

  it("supporte l'absence de stockage", () => {
    expect(() => rememberIdea("idée", null)).not.toThrow();
    expect(pendingIdea(null)).toBeNull();
    expect(() => forgetIdea(null)).not.toThrow();
  });

  it("supporte un stockage qui lève une erreur", () => {
    const broken = {
      getItem: () => { throw new Error("bloqué"); },
      setItem: () => { throw new Error("plein"); },
      removeItem: () => { throw new Error("bloqué"); },
    };
    expect(() => rememberIdea("idée", broken)).not.toThrow();
    expect(pendingIdea(broken)).toBeNull();
    expect(() => forgetIdea(broken)).not.toThrow();
  });
});
