import { api } from "./api";
import { t } from "./i18n";

/** Champs que l'assistant IA sait rédiger (miroir de `FIELD_KINDS` côté API). */
export type AssistKind =
  | "project_title"
  | "theme"
  | "hint"
  | "angle"
  | "bible"
  | "voice_text"
  | "visual_prompt"
  | "reference_prompt"
  | "title"
  | "description"
  | "hashtags";

export type AssistMode = "generate" | "rewrite";

/** Nom court de chaque champ (libellés accessibles des boutons, journal des coûts). */
export const ASSIST_LABELS: Record<AssistKind, string> = {
  project_title: t("titre du projet"),
  theme: t("thème"),
  hint: t("piste de départ"),
  angle: "angle",
  bible: "fiche visuelle",
  voice_text: "voix off",
  visual_prompt: "prompt visuel",
  reference_prompt: t("prompt de l'image"),
  title: t("titre de publication"),
  description: "description",
  hashtags: "hashtags",
};

/** Étape d'un appel du journal des coûts : `assist:<champ>` devient « Assistant IA (voix off) ». */
export function assistStepLabel(step: string): string | null {
  const kind = step.startsWith("assist:") ? (step.slice(7) as AssistKind) : null;
  return kind && kind in ASSIST_LABELS ? `Assistant IA (${ASSIST_LABELS[kind]})` : null;
}

/** Contexte transmis à l'API pour que la proposition reste cohérente avec le projet. */
export interface AssistContext {
  projectId?: number;
  /** Scène enregistrée (absente pour une scène ajoutée et pas encore enregistrée). */
  sceneId?: number;
  /** Durée du brouillon de scène : fixe le budget de mots de la voix off. */
  durationS?: number;
}

export const MAX_INSTRUCTION = 300; // miroir de l'API

export interface AssistBody {
  field_kind: AssistKind;
  mode: AssistMode;
  text: string;
  instruction?: string;
  project_id?: number;
  scene_id?: number;
  duration_s?: number;
}

/** Corps de `POST /ai/assist` : champs vides ou invalides omis, consigne nettoyée. */
export function assistBody(
  kind: AssistKind,
  mode: AssistMode,
  text: string,
  instruction: string,
  { projectId, sceneId, durationS }: AssistContext = {},
): AssistBody {
  const body: AssistBody = { field_kind: kind, mode, text };
  const cleaned = instruction.trim();
  if (cleaned) body.instruction = cleaned;
  if (projectId !== undefined) body.project_id = projectId;
  if (projectId !== undefined && sceneId !== undefined) body.scene_id = sceneId;
  if (durationS !== undefined && Number.isFinite(durationS) && durationS > 0) body.duration_s = durationS;
  return body;
}

/** Raison pour laquelle un bouton de l'assistant est inactif (affichée en infobulle), ou `null`. */
export function assistBlocked(mode: AssistMode, text: string, locked: boolean, loading: boolean): string | null {
  if (loading) return t("Proposition en cours");
  if (locked) return t("Indisponible pendant une génération ou un enregistrement");
  if (mode === "rewrite" && !text.trim()) return t("Saisissez d'abord un texte à reformuler");
  return null;
}

/** Le champ a changé pendant la demande (saisie, annulation du brouillon, mise à jour serveur) : la réponse est
 *  ignorée plutôt que d'écraser ce changement. */
export function replyIsStale(sent: string, current: string): boolean {
  return sent !== current;
}

/** Applique `patch` à l'élément de clé `key` (une réponse tardive vise la bonne scène même après réordonnancement). */
export function patchByKey<T extends { key: string }>(list: T[], key: string, patch: Partial<T>): T[] {
  return list.map((item) => (item.key === key ? { ...item, ...patch } : item));
}

/** Annulation possible tant que le champ contient encore la proposition de l'IA. */
export function canUndo(value: string, applied: { result: string } | null): boolean {
  return applied !== null && applied.result === value;
}

export async function requestAssist(body: AssistBody): Promise<string> {
  return (await api<{ text: string }>("/ai/assist", { method: "POST", body: JSON.stringify(body) })).text;
}
