import { formatCredits } from "./credits";
import { durationText, usd } from "./format";
import { t } from "./i18n";
import { serverText } from "./serverText";

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
  /** Admin : durée d'un clip local ou coût d'un clip cloud ; nuls pour un client. */
  minutes_per_clip: number | null;
  cost_usd_per_clip: number | null;
  /** Client : prix d'un clip de 3 s en crédits (jamais de dollars devant lui) ; nul pour l'admin. */
  credits_per_clip: number | null;
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

export const VIDEO_PROVIDER_LABELS: Record<string, string> = { fal: "fal.ai", comfyui: "ComfyUI", comfycloud: "Comfy Cloud" };

/** Providers qui exécutent nos graphes ComfyUI (`COMFY_PROVIDERS` du backend) : image de départ par Flux Kontext. */
export const COMFY_PROVIDERS = ["comfyui", "comfycloud"];

/** Remplissage des cinq étoiles d'une note sur 5, demi-étoile comprise : 3.5 → full, full, full, half, empty. */
export function starFills(value: number): ("full" | "half" | "empty")[] {
  const full = Math.floor(value);
  const half = value - full >= 0.5 ? 1 : 0;
  return [...Array<"full">(full).fill("full"), ...Array<"half">(half).fill("half"), ...Array<"empty">(5 - full - half).fill("empty")];
}


/** Prix en crédits (client), durée (local) ou coût en dollars (cloud, admin) de `count` clips. */
function cost(card: ModelCard, count: number): string {
  if (card.credits_per_clip !== null) return `≈ ${formatCredits(card.credits_per_clip * count)}`; // clips de 3 s
  return card.minutes_per_clip !== null
    ? `≈ ${durationText(card.minutes_per_clip * count * 60)}`
    : `≈ ${usd.format((card.cost_usd_per_clip ?? 0) * count)}`;
}

export function clipCost(card: ModelCard): string {
  return t("{cost} par clip", { cost: cost(card, 1) });
}

export function totalEstimate(card: ModelCard, scenes: number): string {
  return t(scenes > 1 ? "{cost} pour {n} scènes" : "{cost} pour {n} scène", { cost: cost(card, scenes), n: scenes });
}

/** Anciens noms de modèle, comme `LEGACY_NAMES` du backend (`providers/profiles.py`). */
const LEGACY: Record<string, string> = { workflow: "max" };

/** Choix lançable : l'ancien « workflow » devient Maximum ; un choix indisponible ou inconnu passe sur la carte
 *  recommandée si elle est disponible, sinon sur la première carte disponible (le prix reste affiché sur le bouton de
 *  lancement) ; sans carte disponible, il reste tel quel. */
export function pickable(cards: ModelCard[], choice: Choice): Choice {
  const model = LEGACY[choice.model] ?? choice.model;
  const usable = cards.filter((c) => c.available && !c.locked);
  if (usable.some((c) => c.provider === choice.provider && c.id === model)) return { ...choice, model };
  const target = usable.find((c) => c.recommended) ?? usable[0];
  return target ? { provider: target.provider, model: target.id } : choice;
}

/** Éléments disponibles d'abord, l'ordre d'origine gardé de part et d'autre (tri stable). */
export function availableFirst<T extends { available: boolean }>(items: T[]): T[] {
  return [...items.filter((i) => i.available), ...items.filter((i) => !i.available)];
}

/** Ordre des groupes de cartes (un par provider) : ceux qui ont une carte disponible d'abord, puis, à égalité, le
 *  groupe de la carte recommandée ; sinon l'ordre de l'API. */
export function groupOrder(cards: ModelCard[]): string[] {
  const first = cards.find((c) => c.recommended)?.provider;
  const rank = (p: string) => (cards.some((c) => c.provider === p && c.available) ? 0 : 2) + (p === first ? 0 : 1);
  return [...new Set(cards.map((c) => c.provider))].sort((a, b) => rank(a) - rank(b));
}

/** Raison d'empêcher un lancement de l'étape Clips (affichée, boutons désactivés) : modèles (`cards`) ou choix par
 *  défaut des réglages (`choice` null) pas encore chargés, chargement en erreur (`error`), choix sans carte
 *  disponible. `undefined` : lancement possible. */
export function launchBlocked(cards: ModelCard[] | undefined, error: string | null, choice: Choice | null): string | undefined {
  if (error) return t("Génération impossible : modèles vidéo ou réglages non chargés ({error}).", { error });
  if (!cards) return t("Chargement des modèles vidéo… La génération sera possible ensuite.");
  if (!choice) return t("Chargement des réglages… La génération sera possible ensuite.");
  const card = cards.find((c) => c.provider === choice.provider && c.id === choice.model);
  if (!card) return t("Génération impossible : modèle vidéo inconnu ({model}).", { model: choice.model });
  if (card.locked) return card.locked_reason ? serverText(card.locked_reason) : undefined;
  if (!card.available) return t("Génération impossible : {name} indisponible ({reason}).", { name: t(card.name), reason: serverText(card.reason ?? "") });
  return undefined;
}

/** Générateur de l'image de départ des scènes qui ont des images de référence (réglage `start_image_provider`). */
export const START_IMAGE_LABELS: Record<string, string> = {
  comfyui: t("Flux Kontext (local, gratuit)"),
  gemini: t("Gemini (payant, facturé par scène)"),
};

/** Générateurs de l'image de départ pour le provider des clips : Kontext tourne sur ce provider, payant sur Comfy Cloud. */
export function startImageLabels(videoProvider: string): Record<string, string> {
  return videoProvider === "comfycloud" ? { ...START_IMAGE_LABELS, comfyui: t("Flux Kontext (Comfy Cloud, payant)") } : START_IMAGE_LABELS;
}

export const IMAGE_PROVIDER_LABELS: Record<string, string> = {
  gemini: "Gemini",
  fal: "fal.ai",
  comfyui: t("ComfyUI (local)"),
  comfycloud: "Comfy Cloud",
};

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
  if (error) return t("Génération impossible : modèles d'image non chargés ({error}).", { error });
  if (!cards) return t("Chargement des modèles d'image… La génération sera possible ensuite.");
  const card = imageCard(cards, choice);
  if (!card) return t("Génération impossible : modèle d'image inconnu ({model}).", { model: choice.model });
  if (!card.available) return `${serverText(card.reason)}.`;
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
  return availableFirst(list).map((c) => {
    const provider = IMAGE_PROVIDER_LABELS[c.provider] ?? c.provider;
    return { value: choiceKey({ provider: c.provider, model: c.id }), label: `${c.name} (${provider}${c.available ? "" : ", indisponible"})` };
  });
}

/** Motif d'une carte indisponible pour un client (`UNAVAILABLE` du backend) : déjà complet, sans détail technique. */
const UNAVAILABLE = "Indisponible pour le moment";

/** Mention sous une carte : réservée à l'abonnement, panne (carte grisée) ou avertissement (carte lançable, ex. ComfyUI occupé) ; `null` sans
 *  raison. */
export function cardNotice(card: ModelCard): { kind: "locked" | "unavailable" | "warning"; text: string } | null {
  if (card.locked && card.locked_reason) return { kind: "locked", text: serverText(card.locked_reason) };
  if (card.reason === UNAVAILABLE) return { kind: "unavailable", text: t(UNAVAILABLE) }; // motif neutre d'un client
  if (!card.available) return { kind: "unavailable", text: t("Indisponible : {reason}", { reason: serverText(card.reason) }) };
  if (card.reason) return { kind: "warning", text: t("Attention : {reason}. La génération attendra son tour.", { reason: serverText(card.reason) }) };
  return null;
}
