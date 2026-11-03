/** Histoire d'une vidéo (étape `story`) : beats et éléments suivis, tels que le backend les stocke (`services/story.py`). */

export type ElementKind = "character" | "prop" | "place";
export const ELEMENT_KINDS: Record<ElementKind, string> = { character: "Personnage", prop: "Accessoire", place: "Lieu" };
const ELEMENT_KINDS_PLURAL: Record<ElementKind, string> = { character: "personnages", prop: "accessoires", place: "lieux" };

/** Compteur des éléments suivis par type, ex. « 2 personnages, 1 lieu » ; chaîne vide sans élément. */
export function elementCounts(elements: Pick<StoryElement, "kind">[]): string {
  return (Object.keys(ELEMENT_KINDS) as ElementKind[])
    .map((kind) => [kind, elements.filter((e) => e.kind === kind).length] as const)
    .filter(([, n]) => n > 0)
    .map(([kind, n]) => `${n} ${n > 1 ? ELEMENT_KINDS_PLURAL[kind] : ELEMENT_KINDS[kind].toLowerCase()}`)
    .join(", ");
}

export interface StoryElement {
  id: string;
  kind: ElementKind;
  name: string;
  /** Apparence figée, en anglais : recopiée en tête du prompt visuel de chaque scène où l'élément apparaît. */
  descriptor: string;
  /** Prompt de l'image de référence (vide pour un lieu). */
  prompt: string;
  /** Voix du personnage quand il parle (identifiant du catalogue) ; vide : la voix par défaut. */
  voice_id: string;
}

/** Élément visible dans un beat et son état à cet instant (« dry », « wet »…). */
export interface BeatElement {
  id: string;
  state: string;
}

/** « continue » : le beat suit directement le précédent (même lieu), sa première image est la dernière du précédent ;
 *  « cut » : changement de lieu, il repart des images de référence. */
export type Continuity = "continue" | "cut";
export const CONTINUITY_LABELS: Record<Continuity, string> = {
  continue: "Suite directe du beat précédent",
  cut: "Changement de lieu ou de plan",
};

export interface StoryBeat {
  summary: string;
  voice_text: string;
  duration_s: number;
  continuity: Continuity;
  /** Personnage qui prononce la voix off du beat ; vide : le narrateur. */
  speaker: string;
  elements: BeatElement[];
}

/** Beat du brouillon : `key` stable pour React tant que les beats se déplacent. */
export type DraftBeat = StoryBeat & { key: string };

export interface DraftStory {
  bible: string;
  elements: StoryElement[];
  beats: DraftBeat[];
}

/** Brouillon à partir du `result` de l'étape ; tolère un résultat vide (projet existant) ou incomplet. */
export function storyOf(result: Record<string, unknown> | null | undefined): DraftStory {
  const raw = (result ?? {}) as { bible?: unknown; elements?: Partial<StoryElement>[]; beats?: (Partial<StoryBeat> & { continuity?: string })[] };
  return {
    bible: typeof raw.bible === "string" ? raw.bible : "",
    elements: (Array.isArray(raw.elements) ? raw.elements : []).map(
      (e) => ({ ...e, voice_id: e.voice_id ?? "" }) as StoryElement,
    ),
    beats: (Array.isArray(raw.beats) ? raw.beats : []).map((b, i) => ({
      key: `beat-${i}`,
      summary: b.summary ?? "",
      voice_text: b.voice_text ?? "",
      duration_s: b.duration_s ?? 0,
      continuity: i > 0 && b.continuity === "continue" ? "continue" : "cut",
      speaker: b.speaker ?? "",
      elements: b.elements ?? [],
    })),
  };
}

/** `result` à enregistrer : le brouillon sans clés, les autres champs du résultat (avertissements…) conservés. */
export function toResult(story: DraftStory, previous: Record<string, unknown> | null): Record<string, unknown> {
  return {
    ...previous,
    bible: story.bible.trim(),
    elements: story.elements,
    beats: story.beats.map(({ key: _key, ...beat }, i) => ({ ...beat, continuity: i > 0 ? beat.continuity : "cut" })),
  };
}

/** Ids cités par un beat mais absents des éléments (le backend les refuse), sans doublon. */
export function unknownIds(story: DraftStory): string[] {
  const known = new Set(story.elements.map((e) => e.id));
  return [...new Set(story.beats.flatMap((b) => b.elements.map((e) => e.id)).filter((id) => !known.has(id)))];
}

/** Retire l'élément et ses mentions dans les beats. */
export function withoutElement(story: DraftStory, id: string): DraftStory {
  return {
    ...story,
    elements: story.elements.filter((e) => e.id !== id),
    beats: story.beats.map((b) => ({
      ...b,
      speaker: b.speaker === id ? "" : b.speaker,
      elements: b.elements.filter((e) => e.id !== id),
    })),
  };
}

export const newBeat = (): DraftBeat => ({
  key: crypto.randomUUID(),
  summary: "",
  voice_text: "",
  duration_s: 4,
  continuity: "cut",
  speaker: "",
  elements: [],
});

/** Nouvel élément : l'id vient du nom (minuscules, `a-z0-9_`), rendu unique parmi `taken`. */
export function newElement(name: string, taken: StoryElement[]): StoryElement {
  const base =
    name
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "element";
  const used = new Set(taken.map((e) => e.id));
  let id = base;
  for (let n = 2; used.has(id); n++) id = `${base}_${n}`;
  return { id, kind: "prop", name, descriptor: "", prompt: "", voice_id: "" };
}

export const storyTotal = (beats: StoryBeat[]): number => beats.reduce((sum, b) => sum + (b.duration_s || 0), 0);

/** Index du premier beat sans résumé ou sans voix off (le backend les exige), -1 si aucun. */
export const blankBeat = (beats: StoryBeat[]): number => beats.findIndex((b) => !b.summary.trim() || !b.voice_text.trim());

/** Éléments qui peuvent parler : les personnages. */
export const speakingElements = (elements: StoryElement[]): StoryElement[] => elements.filter((e) => e.kind === "character");
