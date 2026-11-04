import { durationText, usd } from "./format";

/** Modèle de `GET /providers/models` et sa disponibilité (clé `image` : modèles de l'image de référence). */
export interface ModelStatus {
  provider: string;
  id: string;
  name: string;
  /** Lançable. Une carte disponible peut porter une `reason` d'avertissement (ex. ComfyUI occupé : le job attendra). */
  available: boolean;
  reason: string;
}

/** Carte d'un modèle vidéo (`GET /providers/models`, clé `video`) : profil local noté ou modèle cloud facturé. */
export interface ModelCard extends ModelStatus {
  description: string;
  speed: number | null;
  quality: number | null;
  minutes_per_clip: number | null;
  cost_usd_per_clip: number | null;
  /** Profil conseillé (et défaut des réglages) : désigné par le backend (`DEFAULT_PROFILE`). */
  recommended: boolean;
  /** Profil réservé à l'abonnement pour ce compte : visible, mais non choisissable ; `locked_reason` dit pourquoi. */
  locked: boolean;
  locked_reason: string | null;
}

export interface Choice {
  provider: string;
  model: string;
}

export const VIDEO_PROVIDER_LABELS: Record<string, string> = { fal: "fal.ai", comfyui: "ComfyUI" };

/** Remplissage des cinq étoiles d'une note sur 5, demi-étoile comprise : 3.5 → full, full, full, half, empty. */
export function starFills(value: number): ("full" | "half" | "empty")[] {
  const full = Math.floor(value);
  const half = value - full >= 0.5 ? 1 : 0;
  return [...Array<"full">(full).fill("full"), ...Array<"half">(half).fill("half"), ...Array<"empty">(5 - full - half).fill("empty")];
}


/** Durée (local) ou coût (cloud) de `count` clips. */
function cost(card: ModelCard, count: number): string {
  return card.minutes_per_clip !== null
    ? `≈ ${durationText(card.minutes_per_clip * count * 60)}`
    : `≈ ${usd.format((card.cost_usd_per_clip ?? 0) * count)}`;
}

export function clipCost(card: ModelCard): string {
  return `${cost(card, 1)} par clip`;
}

export function totalEstimate(card: ModelCard, scenes: number): string {
  return `${cost(card, scenes)} pour ${scenes} scène${scenes > 1 ? "s" : ""}`;
}

/** Anciens noms de modèle, comme `LEGACY_NAMES` du backend (`providers/profiles.py`). */
const LEGACY: Record<string, string> = { workflow: "max" };

/** Choix lançable : l'ancien « workflow » devient Maximum ; un choix indisponible ou inconnu passe sur la carte
 *  gratuite recommandée si elle est disponible, sinon sur la première carte gratuite disponible (jamais sur une carte
 *  payante : on ne dépense pas sans l'accord de l'utilisateur) ; sans carte gratuite disponible, il reste tel quel. */
export function pickable(cards: ModelCard[], choice: Choice): Choice {
  const model = LEGACY[choice.model] ?? choice.model;
  const usable = cards.filter((c) => c.available && !c.locked);
  if (usable.some((c) => c.provider === choice.provider && c.id === model)) return { ...choice, model };
  const free = usable.filter((c) => c.cost_usd_per_clip === null);
  const target = free.find((c) => c.recommended) ?? free[0];
  return target ? { provider: target.provider, model: target.id } : choice;
}

/** Raison d'empêcher un lancement de l'étape Clips (affichée, boutons désactivés) : modèles (`cards`) ou choix par
 *  défaut des réglages (`choice` null) pas encore chargés, chargement en erreur (`error`), choix sans carte
 *  disponible. `undefined` : lancement possible. */
export function launchBlocked(cards: ModelCard[] | undefined, error: string | null, choice: Choice | null): string | undefined {
  if (error) return `Génération impossible : modèles vidéo ou réglages non chargés (${error}).`;
  if (!cards) return "Chargement des modèles vidéo… La génération sera possible ensuite.";
  if (!choice) return "Chargement des réglages… La génération sera possible ensuite.";
  const card = cards.find((c) => c.provider === choice.provider && c.id === choice.model);
  if (!card) return `Génération impossible : modèle vidéo inconnu (${choice.model}).`;
  if (card.locked) return card.locked_reason ?? undefined;
  if (!card.available) return `Génération impossible : ${card.name} indisponible (${card.reason}).`;
  return undefined;
}

/** Générateur de l'image de départ des scènes qui ont des images de référence (réglage `start_image_provider`). */
export const START_IMAGE_LABELS: Record<string, string> = {
  comfyui: "Flux Kontext (local, gratuit)",
  gemini: "Gemini (payant, environ 0,08 $ par scène)",
};

export const IMAGE_PROVIDER_LABELS: Record<string, string> = { gemini: "Gemini", fal: "fal.ai", comfyui: "ComfyUI (local)" };

/** Modèle d'image du choix, parmi les cartes `image` de `/providers/models`. */
function imageCard(cards: ModelStatus[], choice: Choice): ModelStatus | undefined {
  return cards.find((c) => c.provider === choice.provider && c.id === choice.model);
}

/** Choix de l'image de référence : celui enregistré sur l'étape (un ancien `model: flux` sans provider vaut fal) s'il
 *  est disponible, sinon le premier modèle disponible du provider par défaut (réglage `image_provider`), sinon le
 *  premier disponible ; sans modèle disponible (ou avant le chargement), le choix enregistré ou le défaut, pour que
 *  la raison du blocage s'affiche. */
export function imageChoice(
  cards: ModelStatus[] | undefined,
  saved: { provider?: string; model?: string },
  defaultProvider: string,
): Choice {
  const provider = saved.provider ?? (saved.model === "flux" ? "fal" : defaultProvider);
  const wanted = { provider, model: saved.model ?? cards?.find((c) => c.provider === provider)?.id ?? "" };
  if (!cards || imageCard(cards, wanted)?.available) return wanted;
  const usable = cards.filter((c) => c.available);
  const target = usable.find((c) => c.provider === defaultProvider) ?? usable[0];
  return target ? { provider: target.provider, model: target.id } : wanted;
}

/** Raison d'empêcher la génération de l'image de référence (affichée, bouton désactivé) : modèles pas encore chargés
 *  ou en erreur, modèle inconnu ou indisponible (la raison du serveur, affichée seule, dit où saisir la clé
 *  manquante). `undefined` : lancement possible. */
export function imageBlocked(cards: ModelStatus[] | undefined, error: string | null, choice: Choice): string | undefined {
  if (error) return `Génération impossible : modèles d'image non chargés (${error}).`;
  if (!cards) return "Chargement des modèles d'image… La génération sera possible ensuite.";
  const card = imageCard(cards, choice);
  if (!card) return `Génération impossible : modèle d'image inconnu (${choice.model}).`;
  if (!card.available) return `${card.reason}.`;
  return undefined;
}

/** Valeur d'option d'un choix (`provider/modèle`) et choix d'une valeur. */
export const choiceKey = (choice: Choice) => `${choice.provider}/${choice.model}`;
export function choiceOf(value: string): Choice {
  const [provider, ...model] = value.split("/");
  return { provider, model: model.join("/") };
}

/** Options du choix de l'image de référence : chaque modèle avec son provider en clair (« (indisponible) » s'il ne
 *  l'est pas) ; avant le chargement, le choix courant seul. */
export function imageOptions(cards: ModelStatus[] | undefined, current: Choice): { value: string; label: string }[] {
  const list = cards ?? [{ provider: current.provider, id: current.model, name: current.model, available: true, reason: "" }];
  return list.map((c) => {
    const provider = IMAGE_PROVIDER_LABELS[c.provider] ?? c.provider;
    return { value: choiceKey({ provider: c.provider, model: c.id }), label: `${c.name} (${provider}${c.available ? "" : ", indisponible"})` };
  });
}

/** Mention sous une carte : réservée à l'abonnement, panne (carte grisée) ou avertissement (carte lançable, ex. ComfyUI occupé) ; `null` sans
 *  raison. */
export function cardNotice(card: ModelCard): { kind: "locked" | "unavailable" | "warning"; text: string } | null {
  if (card.locked && card.locked_reason) return { kind: "locked", text: card.locked_reason };
  if (!card.available) return { kind: "unavailable", text: `Indisponible : ${card.reason}` };
  if (card.reason) return { kind: "warning", text: `Attention : ${card.reason}. La génération attendra son tour.` };
  return null;
}
