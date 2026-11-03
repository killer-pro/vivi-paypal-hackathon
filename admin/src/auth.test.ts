import { describe, expect, it } from "vitest";
import { isPublicPath, tokenFromSearch, validPassword, visibleNav } from "./auth";

describe("visibleNav", () => {
  const items = [{ to: "/" }, { to: "/music", adminOnly: true }, { to: "/costs", adminOnly: false }];

  it("masque les entrées réservées à l'administrateur pour un utilisateur", () => {
    expect(visibleNav(items, "user").map((i) => i.to)).toEqual(["/", "/costs"]);
  });

  it("garde tout pour l'administrateur", () => {
    expect(visibleNav(items, "admin")).toEqual(items);
  });
});

describe("tokenFromSearch", () => {
  it("lit le jeton de l'URL", () => {
    expect(tokenFromSearch("?token=abc")).toBe("abc");
  });

  it("renvoie null sans jeton", () => {
    expect(tokenFromSearch("")).toBeNull();
    expect(tokenFromSearch("?x=1")).toBeNull();
    expect(tokenFromSearch("?token=")).toBeNull();
  });
});

describe("validPassword", () => {
  it("accepte de 8 à 128 caractères", () => {
    expect(validPassword("a".repeat(7))).toBe(false);
    expect(validPassword("a".repeat(8))).toBe(true);
    expect(validPassword("a".repeat(128))).toBe(true);
    expect(validPassword("a".repeat(129))).toBe(false);
  });
});

describe("isPublicPath", () => {
  it("reconnaît les écrans hors session", () => {
    for (const path of ["/decouvrir", "/login", "/register", "/verify", "/forgot", "/reset"]) expect(isPublicPath(path)).toBe(true);
  });

  it("refuse les écrans connectés", () => {
    expect(isPublicPath("/")).toBe(false);
    expect(isPublicPath("/costs")).toBe(false);
  });
});
