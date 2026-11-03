import { describe, expect, it } from "vitest";
import { plainTitle } from "./format";

describe("plainTitle", () => {
  it("retire les emoji et les espaces qu'ils laissent", () => {
    expect(plainTitle("⏱️ Découpage Vidéo (58s au total)")).toBe("Découpage Vidéo (58s au total)");
  });
  it("garde le texte, les accents et la ponctuation", () => {
    expect(plainTitle("Pourquoi la pieuvre est le génie des océans ?")).toBe("Pourquoi la pieuvre est le génie des océans ?");
  });
});
