import { describe, expect, it } from "vitest";
import {
  canCreate,
  DURATIONS,
  fromTemplate,
  MAX_DURATION_S,
  MIN_DURATION_S,
  parseDuration,
  styleOptions,
  titleFromSubject,
} from "./newVideo";
import { TEMPLATES } from "./templates";

describe("titleFromSubject", () => {
  it("prend la première ligne et condense les espaces", () => {
    expect(titleFromSubject("  3 astuces   pour dormir\nton direct")).toBe("3 astuces pour dormir");
  });
  it("coupe au mot en dessous de 60 caractères", () => {
    const title = titleFromSubject("Pourquoi les chats retombent toujours sur leurs pattes même quand ils tombent de haut");
    expect(title.length).toBeLessThanOrEqual(60);
    expect(title.endsWith("…")).toBe(true);
    expect(title).not.toMatch(/\s…$/);
  });
  it("coupe net un mot unique trop long", () => {
    expect(titleFromSubject("a".repeat(80))).toBe(`${"a".repeat(59)}…`);
  });
  it("donne un titre par défaut à un sujet vide", () => {
    expect(titleFromSubject("   ")).toBe("Nouvelle vidéo");
  });
});

describe("parseDuration", () => {
  it("accepte un entier de 5 à 180 s", () => {
    expect(parseDuration("5")).toBe(MIN_DURATION_S);
    expect(parseDuration(" 45 ")).toBe(45);
    expect(parseDuration("180")).toBe(MAX_DURATION_S);
  });
  it("refuse ce qui est hors bornes ou n'est pas un entier", () => {
    for (const bad of ["", "4", "181", "0", "-30", "12,5", "abc"]) expect(parseDuration(bad)).toBeNull();
  });
});

describe("canCreate", () => {
  it("exige une idée non vide et une durée valide", () => {
    expect(canCreate("  ", "30")).toBe(false);
    expect(canCreate("Les chats", "300")).toBe(false);
    expect(canCreate("Les chats", "30")).toBe(true);
  });
});

describe("fromTemplate", () => {
  it("remplit l'idée, la durée et la durée de scène du modèle", () => {
    const t = TEMPLATES[1];
    expect(fromTemplate(t)).toEqual({ subject: t.subject, duration: String(t.duration_s), sceneLength: t.scene_length_s });
  });
  it("ne propose que des durées rapides valides", () => {
    for (const t of TEMPLATES) expect(DURATIONS).toContain(t.duration_s);
    expect(DURATIONS).toEqual([15, 30, 45, 60]);
  });
});

describe("styleOptions", () => {
  it("met « Aucun » en premier puis les styles du serveur, un seul choix possible", () => {
    const options = styleOptions([
      { id: "realistic", label: "Réaliste" },
      { id: "anime", label: "Anime" },
    ]);
    expect(options).toEqual([
      { value: "", label: "Aucun" },
      { value: "realistic", label: "Réaliste" },
      { value: "anime", label: "Anime" },
    ]);
  });
});

describe("styleOptions réservés", () => {
  it("garde les styles réservés visibles mais non choisissables", () => {
    const options = styleOptions(
      [
        { id: "realistic", label: "Réaliste" },
        { id: "anime", label: "Anime" },
      ],
      ["anime"],
      "Réservé à l'abonnement : les styles visuels",
    );
    expect(options).toEqual([
      { value: "", label: "Aucun" },
      { value: "realistic", label: "Réaliste" },
      { value: "anime", label: "Anime", disabled: true, hint: "Réservé à l'abonnement : les styles visuels" },
    ]);
  });
});
