import { afterEach, describe, expect, it, vi } from "vitest";
import { en } from "./locales/en";

/** Charge `i18n.ts` comme si la page avait été ouverte avec cette adresse et ce stockage. */
async function load(search = "", stored: string | null = null) {
  vi.resetModules();
  const storage = new Map<string, string>(stored ? [["vivi.lang", stored]] : []);
  vi.stubGlobal("location", { search });
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => storage.set(k, v),
  });
  return { i18n: await import("./i18n"), storage };
}

afterEach(() => vi.unstubAllGlobals());

describe("langue de l'interface", () => {
  it("reste en français par défaut", async () => {
    const { i18n } = await load();
    expect(i18n.lang).toBe("fr");
    expect(i18n.t("Idée")).toBe("Idée");
  });

  it("suit ?lang=en et le mémorise", async () => {
    const { i18n, storage } = await load("?lang=en");
    expect(i18n.lang).toBe("en");
    expect(i18n.t("Valider")).toBe("Approve");
    expect(storage.get("vivi.lang")).toBe("en");
  });

  it("reprend le dernier choix, ignore une langue inconnue", async () => {
    expect((await load("", "en")).i18n.lang).toBe("en");
    expect((await load("?lang=de", "fr")).i18n.lang).toBe("fr");
  });

  it("garde le français pour un texte sans traduction", async () => {
    const { i18n } = await load("?lang=en");
    expect(i18n.t("Un texte jamais traduit")).toBe("Un texte jamais traduit");
  });

  it("remplace les variables et choisit le singulier ou le pluriel", async () => {
    const { i18n } = await load("?lang=en");
    expect(i18n.t("scène {n}", { n: 3 })).toBe("scene 3");
    expect(i18n.tn(1, "{n} scène", "{n} scènes")).toBe("1 scene");
    expect(i18n.tn(2, "{n} scène", "{n} scènes")).toBe("2 scenes");
    expect((await load()).i18n.tn(2, "{n} scène", "{n} scènes")).toBe("2 scènes");
  });
});

describe("motifs du registre de crédits", () => {
  it("sont traduits, sauf un motif saisi à la main", async () => {
    await load("?lang=en");
    const { reasonLabel } = await import("./credits");
    expect(reasonLabel("Recharge de 200 crédits")).toBe("Top-up of 200 credits");
    expect(reasonLabel("Crédits d'abonnement du mois (400)")).toBe("Monthly subscription credits (400)");
    expect(reasonLabel("Génération : les clips")).toBe("Generation: the clips");
    expect(reasonLabel("Geste commercial")).toBe("Geste commercial");
  });
});

describe("messages écrits par le serveur", () => {
  it("sont traduits selon leur modèle, sinon laissés tels quels", async () => {
    await load("?lang=en");
    const { serverText } = await import("./serverText");
    expect(serverText("Clé API fal manquante, à saisir dans Réglages → fal.ai")).toBe("fal API key missing, enter it in Settings → fal.ai");
    expect(serverText("Réservé au forfait Créateur : le profil Maximum")).toBe("Creator plan and above: the Maximum profile");
    expect(serverText("Indisponible : les styles visuels")).toBe("Unavailable: the visual styles");
    expect(serverText("19 $ par mois")).toBe("$19 per month");
    expect(serverText("Autre message")).toBe("Autre message");
  });
});

describe("dictionnaire anglais", () => {
  /** Code de l'interface, hors tests et dictionnaire. */
  const sources = Object.entries(
    import.meta.glob<string>(["./**/*.{ts,tsx}", "!./**/*.test.*", "!./locales/**"], { query: "?raw", import: "default", eager: true }),
  );

  it("traduit chaque texte passé tel quel à t(\"…\")", () => {
    expect(sources.length).toBeGreaterThan(20); // le glob trouve bien le code
    const missing = sources.flatMap(([file, code]) =>
      [...code.matchAll(/\bt\("((?:[^"\\]|\\.)*)"/g)]
        .map((m) => JSON.parse(`"${m[1]}"`) as string)
        .filter((key) => !(key in en))
        .map((key) => `${file}: ${key}`),
    );
    expect(missing).toEqual([]);
  });

  it("garde les mêmes {variables} que le français", () => {
    const vars = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();
    const broken = Object.entries(en).filter(([fr, text]) => !text || vars(fr).join() !== vars(text).join());
    expect(broken.map(([fr]) => fr)).toEqual([]);
  });
});
