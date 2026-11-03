import { describe, expect, it } from "vitest";
import {
  cardNotice,
  clipCost,
  starFills,
  choiceOf,
  imageBlocked,
  imageChoice,
  imageOptions,
  launchBlocked,
  pickable,
  totalEstimate,
  type ModelCard,
  type ModelStatus,
} from "./models";

const card = (over: Partial<ModelCard>): ModelCard => ({
  provider: "comfyui",
  id: "fast",
  name: "Rapide",
  description: "",
  speed: 4,
  quality: 3.5,
  minutes_per_clip: 5,
  cost_usd_per_clip: null,
  available: true,
  reason: "",
  recommended: false,
  locked: false,
  locked_reason: null,
  ...over,
});

const local = (minutes: number) => card({ minutes_per_clip: minutes });
const cloud = (cost: number) =>
  card({ provider: "fal", id: "kling", name: "kling", speed: null, quality: null, minutes_per_clip: null, cost_usd_per_clip: cost });

describe("starFills", () => {
  it("donne cinq positions, demi-étoile comprise", () => {
    expect(starFills(1)).toEqual(["full", "empty", "empty", "empty", "empty"]);
    expect(starFills(3.5)).toEqual(["full", "full", "full", "half", "empty"]);
    expect(starFills(5)).toEqual(["full", "full", "full", "full", "full"]);
  });
});

describe("clipCost", () => {
  it("donne la durée d'un clip local", () => {
    expect(clipCost(local(7.5))).toBe("≈ 7 min 30 s par clip");
    expect(clipCost(local(5))).toBe("≈ 5 min par clip");
  });
  it("donne le coût d'un clip cloud", () => {
    expect(clipCost(cloud(0.28))).toBe("≈ 0,28\u00a0$ par clip");
  });
});

describe("totalEstimate", () => {
  it("multiplie la durée locale par le nombre de scènes", () => {
    expect(totalEstimate(local(7.5), 6)).toBe("≈ 45 min pour 6 scènes");
    expect(totalEstimate(local(18), 6)).toBe("≈ 1 h 48 min pour 6 scènes");
    expect(totalEstimate(local(5), 1)).toBe("≈ 5 min pour 1 scène");
  });
  it("multiplie le coût cloud par le nombre de scènes", () => {
    expect(totalEstimate(cloud(0.28), 6)).toBe("≈ 1,68\u00a0$ pour 6 scènes");
    expect(totalEstimate(cloud(0.28), 1)).toBe("≈ 0,28\u00a0$ pour 1 scène");
  });
});

describe("pickable", () => {
  const cards = [
    card({ id: "fast", recommended: true }),
    card({ id: "balanced" }),
    { ...cloud(0.28), available: false, reason: "Clé fal manquante" },
  ];
  it("garde un choix disponible", () => {
    expect(pickable(cards, { provider: "comfyui", model: "balanced" })).toEqual({ provider: "comfyui", model: "balanced" });
  });
  it("traduit l'ancien modèle « workflow » en Maximum, comme le backend", () => {
    const withMax = [...cards, card({ id: "max" })];
    expect(pickable(withMax, { provider: "comfyui", model: "workflow" })).toEqual({ provider: "comfyui", model: "max" });
  });
  it("ramène « workflow » sur la carte recommandée si Maximum est indisponible", () => {
    const noMax = [...cards, card({ id: "max", available: false })];
    expect(pickable(noMax, { provider: "comfyui", model: "workflow" })).toEqual({ provider: "comfyui", model: "fast" });
  });
  it("ne bascule jamais d'un choix local vers une carte payante", () => {
    const comfyDown = [card({ id: "fast", available: false }), card({ id: "balanced", available: false }), cloud(0.28)];
    expect(pickable(comfyDown, { provider: "comfyui", model: "fast" })).toEqual({ provider: "comfyui", model: "fast" });
  });
  it("ramène un choix indisponible sur la première carte disponible si la recommandée ne l'est pas", () => {
    const down = [card({ id: "fast", available: false }), card({ id: "balanced" }), cards[2]];
    expect(pickable(down, { provider: "fal", model: "kling" })).toEqual({ provider: "comfyui", model: "balanced" });
  });
  it("suit la carte recommandée désignée par l'API (champ `recommended`)", () => {
    const other = [card({ id: "fast" }), card({ id: "balanced", recommended: true }), card({ id: "max", available: false })];
    expect(pickable(other, { provider: "comfyui", model: "max" })).toEqual({ provider: "comfyui", model: "balanced" });
  });
  it("laisse le choix inchangé si aucune carte n'est disponible", () => {
    const none = cards.map((c) => ({ ...c, available: false }));
    expect(pickable(none, { provider: "fal", model: "kling" })).toEqual({ provider: "fal", model: "kling" });
  });
});

describe("launchBlocked", () => {
  const cards = [card({ id: "fast" }), { ...cloud(0.28), available: false, reason: "Clé fal manquante" }];
  const fast = { provider: "comfyui", model: "fast" };
  it("bloque tant que les modèles ne sont pas chargés", () => {
    expect(launchBlocked(undefined, null, fast)).toBe("Chargement des modèles vidéo… La génération sera possible ensuite.");
  });
  it("bloque si les modèles ou les réglages n'ont pas pu être chargés", () => {
    expect(launchBlocked(undefined, "Erreur réseau", fast)).toBe(
      "Génération impossible : modèles vidéo ou réglages non chargés (Erreur réseau).",
    );
    expect(launchBlocked(cards, "Erreur réseau", null)).toBe(
      "Génération impossible : modèles vidéo ou réglages non chargés (Erreur réseau).",
    );
  });
  it("bloque tant que le choix par défaut (réglages) n'est pas connu", () => {
    expect(launchBlocked(cards, null, null)).toBe("Chargement des réglages… La génération sera possible ensuite.");
  });
  it("bloque un choix inconnu ou indisponible, avec sa raison", () => {
    expect(launchBlocked(cards, null, { provider: "comfyui", model: "turbo" })).toBe(
      "Génération impossible : modèle vidéo inconnu (turbo).",
    );
    expect(launchBlocked(cards, null, { provider: "fal", model: "kling" })).toBe(
      "Génération impossible : kling indisponible (Clé fal manquante).",
    );
  });
  it("laisse lancer un choix disponible", () => {
    expect(launchBlocked(cards, null, fast)).toBeUndefined();
  });
});

describe("ComfyUI occupé (carte disponible avec une raison)", () => {
  const busy = (id: string) => card({ id, reason: "ComfyUI ne répond pas (occupé ?)" });
  const cards = [busy("fast"), busy("max")];
  it("reste un choix lançable", () => {
    expect(pickable(cards, { provider: "comfyui", model: "max" })).toEqual({ provider: "comfyui", model: "max" });
    expect(launchBlocked(cards, null, { provider: "comfyui", model: "max" })).toBeUndefined();
  });
  it("affiche un avertissement, pas « Indisponible »", () => {
    expect(cardNotice(busy("fast"))).toEqual({
      kind: "warning",
      text: "Attention : ComfyUI ne répond pas (occupé ?). La génération attendra son tour.",
    });
  });
  it("garde « Indisponible » pour une vraie panne, rien sans raison", () => {
    expect(cardNotice(card({ available: false, reason: "ComfyUI injoignable" }))).toEqual({
      kind: "unavailable",
      text: "Indisponible : ComfyUI injoignable",
    });
    expect(cardNotice(card({}))).toBeNull();
  });
});

describe("modèles d'image (image de référence)", () => {
  const MISSING = "Clé API fal manquante, à saisir dans Réglages → fal.ai";
  const image = (over: Partial<ModelStatus> = {}): ModelStatus => ({
    provider: "gemini",
    id: "gemini-3.1-flash-image",
    name: "gemini-3.1-flash-image",
    available: true,
    reason: "",
    ...over,
  });
  const flux = (over: Partial<ModelStatus> = {}) => image({ provider: "fal", id: "flux", name: "flux", ...over });
  const gemini = { provider: "gemini", model: "gemini-3.1-flash-image" };
  const fal = { provider: "fal", model: "flux" };

  it("bloque tant que les modèles ne sont pas chargés, ou en erreur", () => {
    expect(imageBlocked(undefined, null, gemini)).toBe("Chargement des modèles d'image… La génération sera possible ensuite.");
    expect(imageBlocked(undefined, "Erreur réseau", gemini)).toBe(
      "Génération impossible : modèles d'image non chargés (Erreur réseau).",
    );
  });
  it("bloque un modèle inconnu ou indisponible, avec la raison du serveur seule (sans préfixe en double)", () => {
    expect(imageBlocked([image()], null, { provider: "gemini", model: "dalle" })).toBe(
      "Génération impossible : modèle d'image inconnu (dalle).",
    );
    expect(imageBlocked([image(), flux({ available: false, reason: MISSING })], null, fal)).toBe(`${MISSING}.`);
    const kling = { ...cloud(0.28), available: false, reason: MISSING };
    expect(launchBlocked([kling], null, { provider: "fal", model: "kling" })).toBe(
      "Génération impossible : kling indisponible (Clé API fal manquante, à saisir dans Réglages → fal.ai).",
    );
  });
  it("laisse lancer un modèle disponible", () => {
    expect(imageBlocked([image(), flux()], null, fal)).toBeUndefined();
  });

  it("garde le choix enregistré s'il est disponible", () => {
    expect(imageChoice([image(), flux()], fal, "gemini")).toEqual(fal);
  });
  it("lit un ancien choix « flux » sans provider comme fal", () => {
    expect(imageChoice([image(), flux()], { model: "flux" }, "gemini")).toEqual(fal);
  });
  it("prend le provider par défaut s'il est disponible, sinon le premier disponible", () => {
    const cards = [image(), flux({ available: false, reason: MISSING })];
    expect(imageChoice(cards, {}, "gemini")).toEqual(gemini);
    expect(imageChoice(cards, fal, "fal")).toEqual(gemini); // fal sans clé : Gemini disponible le remplace
    expect(imageChoice([image({ available: false }), flux()], {}, "gemini")).toEqual(fal);
  });
  it("sans modèle disponible (ou avant le chargement), garde le choix ou le défaut, pour afficher la raison", () => {
    const none = [image({ available: false }), flux({ available: false })];
    expect(imageChoice(none, fal, "gemini")).toEqual(fal);
    expect(imageChoice(none, {}, "gemini")).toEqual(gemini);
    expect(imageChoice(undefined, {}, "gemini")).toEqual({ provider: "gemini", model: "" });
  });

  it("propose chaque modèle avec son provider en clair, marque ceux indisponibles", () => {
    expect(imageOptions([image(), flux({ available: false })], fal)).toEqual([
      { value: "gemini/gemini-3.1-flash-image", label: "gemini-3.1-flash-image (Gemini)" },
      { value: "fal/flux", label: "flux (fal.ai, indisponible)" },
    ]);
    expect(imageOptions(undefined, fal)).toEqual([{ value: "fal/flux", label: "flux (fal.ai)" }]);
    expect(choiceOf("fal/flux")).toEqual(fal);
  });
});

describe("profil réservé à l'abonnement", () => {
  const reason = "Réservé à l'abonnement : le profil Précision";
  const locked = card({ id: "precision", name: "Précision", locked: true, locked_reason: reason });

  it("n'est jamais choisi automatiquement, même s'il est le choix enregistré", () => {
    const cards = [card({ id: "fast", recommended: true }), locked];
    expect(pickable(cards, { provider: "comfyui", model: "precision" })).toEqual({ provider: "comfyui", model: "fast" });
  });
  it("bloque le lancement avec son motif quand le choix y est resté", () => {
    expect(launchBlocked([locked], null, { provider: "comfyui", model: "precision" })).toBe(reason);
  });
  it("s'affiche avec son motif, sans « Indisponible »", () => {
    expect(cardNotice(locked)).toEqual({ kind: "locked", text: reason });
  });
});
