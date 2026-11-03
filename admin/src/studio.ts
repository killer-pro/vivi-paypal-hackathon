import type { Asset, ProjectDetail, QueuedRun, Scene } from "./api";
import { currentStep, STEP_LABELS, STOPPED_BY_USER, type Step, type StepName } from "./steps";

/** Outils du rail de l'éditeur : chacun regroupe une ou plusieurs étapes (la référence, facultative, vit dans Clips). */
export const TOOLS = [
  { id: "idea", label: "Idée", steps: ["idea"] },
  { id: "script", label: "Script", steps: ["story", "script"] },
  { id: "clips", label: "Clips", steps: ["reference", "clips"] },
  { id: "voice", label: "Voix", steps: ["voice"] },
  { id: "music", label: "Musique", steps: ["music"] },
  { id: "montage", label: "Montage", steps: ["montage"] },
  { id: "export", label: "Export", steps: ["final"] },
] as const satisfies readonly { id: string; label: string; steps: readonly StepName[] }[];

export type Tool = (typeof TOOLS)[number];
export type ToolId = Tool["id"];

/** Outil qui contient l'étape. */
export function toolOf(step: StepName): Tool {
  return TOOLS.find((t) => (t.steps as readonly StepName[]).includes(step))!;
}

/** Étape ouverte par un clic sur l'outil : l'étape courante si elle en fait partie, sinon son étape principale. */
export function toolStep(tool: Tool, current: StepName): StepName {
  return (tool.steps as readonly StepName[]).includes(current) ? current : tool.steps[tool.steps.length - 1];
}

export type ToolState = "todo" | "running" | "awaiting" | "approved" | "failed";

export const TOOL_STATE_LABELS: Record<ToolState, string> = {
  todo: "à faire",
  running: "en cours",
  awaiting: "à valider",
  approved: "validé",
  failed: "en échec",
};

/** Statuts d'une étape lancée (pour l'étape facultative, qui sinon ne compte pas). */
const LAUNCHED: Step["status"][] = ["running", "failed", "awaiting_validation", "stale"];

/** Pastille d'un outil, de la plus urgente à la plus calme. L'étape facultative ne compte que si elle a été lancée.
 *  Une étape périmée (`stale`) est « à valider » : on peut la régénérer ou la valider telle quelle. */
export function toolState(tool: Tool, steps: Pick<Step, "name" | "status">[]): ToolState {
  const mine = steps.filter(
    (s) => (tool.steps as readonly StepName[]).includes(s.name) && (s.name !== "reference" || LAUNCHED.includes(s.status)),
  );
  const has = (...st: Step["status"][]) => mine.some((s) => st.includes(s.status));
  if (has("running")) return "running";
  if (has("failed")) return "failed";
  if (has("awaiting_validation", "stale")) return "awaiting";
  if (mine.length > 0 && mine.every((s) => s.status === "approved")) return "approved";
  return "todo";
}

export interface Block {
  start: number;
  duration: number;
  /** Position et largeur en % de la durée totale. */
  left: number;
  width: number;
}

/** Blocs de scène de la timeline : largeur proportionnelle à la durée. */
export function timeline(scenes: Pick<Scene, "duration_s">[]): { blocks: Block[]; total: number } {
  const total = scenes.reduce((sum, s) => sum + Math.max(0, s.duration_s || 0), 0);
  let start = 0;
  const blocks = scenes.map((s) => {
    const duration = Math.max(0, s.duration_s || 0);
    const block = {
      start,
      duration,
      left: total ? (start / total) * 100 : 0,
      width: total ? (duration / total) * 100 : 0,
    };
    start += duration;
    return block;
  });
  return { blocks, total };
}

/** Tolérance d'arrondi : un placement au début d'une scène (temps du rendu remis à l'échelle) relu à 8,99999 s
 *  reste dans la scène qui commence à 9 s. */
const EPSILON_S = 0.01;

/** Index de la scène jouée au temps `t` (bornée à la première et à la dernière). */
export function sceneAt(blocks: Block[], t: number): number {
  if (blocks.length === 0) return -1;
  const i = blocks.findIndex((b) => t + EPSILON_S < b.start + b.duration);
  return i === -1 ? blocks.length - 1 : i;
}

/** Graduations de la règle : une par seconde (par 5 s au-delà d'une minute), libellé toutes les 5 s (10 s), sauf
 *  en bout de règle où il déborderait (la durée totale s'affiche sous l'aperçu). */
export function rulerTicks(total: number): { t: number; label: boolean }[] {
  const step = total > 60 ? 5 : 1;
  const every = total > 60 ? 10 : 5;
  const ticks = [];
  for (let t = 0; t <= total; t += step) ticks.push({ t, label: t % every === 0 && total - t >= step * 2 });
  return ticks;
}

/** Le rendu final peut servir d'aperçu : le montage est produit et à jour (ni périmé par un clip modifié, ni relancé,
 *  ni en échec). Sinon l'aperçu montre le clip de la scène, qui reflète les modifications en cours. */
export function renderIsCurrent(steps: Pick<Step, "name" | "status">[]): boolean {
  const montage = steps.find((s) => s.name === "montage")?.status;
  return montage === "approved" || montage === "awaiting_validation";
}

/** Pourquoi « Exporter » est indisponible (infobulle du bouton grisé), ou `null` quand le rendu est à jour. */
export function exportBlockedReason(steps: Pick<Step, "name" | "status">[], hasRender: boolean): string | null {
  if (renderIsCurrent(steps)) return hasRender ? null : "Disponible après le montage";
  return hasRender ? "Le rendu n'est plus à jour : relancez le montage pour l'exporter" : "Disponible après le montage";
}

/** Phrase à afficher quand une étape vient de quitter `running` entre deux chargements du projet, `null` sinon. */
export function completionMessage(before: Step[] | undefined, after: Step[]): string | null {
  const done = after.find((s) => s.status !== "running" && before?.find((b) => b.name === s.name)?.status === "running");
  if (!done) return null;
  const label = STEP_LABELS[done.name];
  if (done.status === "failed") return done.error === STOPPED_BY_USER ? `${label} : arrêtée` : `${label} : échec`;
  return done.status === "awaiting_validation" ? `${label} : à valider` : `${label} : terminée`;
}

/** Ids des scènes après avoir déplacé celle d'`index` de `delta` rangs ; `null` si elle est déjà au bord. */
export function reorderedIds(ids: number[], index: number, delta: -1 | 1): number[] | null {
  const to = index + delta;
  if (to < 0 || to >= ids.length) return null;
  const next = [...ids];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}

/** Scène voisine (← →), bornée. */
export function neighbourScene(index: number, delta: number, count: number): number {
  return Math.min(Math.max(index + delta, 0), Math.max(count - 1, 0));
}

export type LaneState = "ready" | "generating" | "empty";

/** État d'un bloc de piste : média présent, en cours de génération (étape en cours), ou vide. */
export function laneState(hasMedia: boolean, stepRunning: boolean): LaneState {
  if (hasMedia) return "ready";
  return stepRunning ? "generating" : "empty";
}

/** Premiers mots du texte, pour un bloc étroit. */
export function shortText(text: string, words = 4): string {
  const list = text.trim().split(/\s+/).filter(Boolean);
  return list.length > words ? `${list.slice(0, words).join(" ")}…` : list.join(" ");
}

/** Scènes qui ont au moins un média du type. */
function scenesWith(project: Pick<ProjectDetail, "scenes" | "assets">, kind: Asset["kind"]): number {
  const ids = new Set(project.assets.filter((a) => a.kind === kind).map((a) => a.scene_id));
  return project.scenes.filter((s) => ids.has(s.id)).length;
}

/** Libellé de l'autopilot : l'étape en cours (ou à venir) et, pour les clips et les voix, scènes prêtes / total. */
export function autopilotLabel(project: Pick<ProjectDetail, "steps" | "scenes" | "assets">): string {
  const step = project.steps.find((s) => s.status === "running")?.name ?? currentStep(project.steps);
  const label = STEP_LABELS[step];
  const kind = step === "clips" ? "clip" : step === "voice" ? "voice" : null;
  if (!kind || project.scenes.length === 0) return label;
  return `${label} ${scenesWith(project, kind)}/${project.scenes.length}`;
}

export type Shortcut = "toggle" | "prev" | "next";

/** Raccourci clavier de l'éditeur, ou `null` si la touche revient au contrôle focalisé : champ de saisie, liste,
 *  lecteur audio/vidéo, bouton ou lien (espace les active), groupe de boutons radio (flèches). Les blocs de la timeline (`scene`)
 *  laissent passer l'espace (lecture) et les flèches (scène voisine). */
export function shortcutFor(key: string, target: { tag: string; role?: string | null; scene?: boolean }): Shortcut | null {
  const tag = target.tag.toLowerCase();
  if (["input", "textarea", "select", "audio", "video"].includes(tag) || target.role === "radio" || target.role === "textbox")
    return null;
  const interactive = ["button", "a", "summary"].includes(tag) && !target.scene;
  if (key === " ") return interactive ? null : "toggle";
  if (key === "ArrowLeft") return "prev";
  if (key === "ArrowRight") return "next";
  return null;
}

/** Durée pendant laquelle une URL présignée est réutilisée (elles expirent après 1 h). */
const URL_REUSE_MS = 30 * 60 * 1000;

/** Date de signature d'une URL présignée S3 (`X-Amz-Date=AAAAMMJJTHHMMSSZ`), en ms ; 0 si absente. */
function signedAt(url: string): number {
  const d = /[?&]X-Amz-Date=(\d{8}T\d{6}Z)/.exec(url)?.[1];
  if (!d) return 0;
  const n = (from: number, to: number) => Number(d.slice(from, to));
  return Date.UTC(n(0, 4), n(4, 6) - 1, n(6, 8), n(9, 11), n(11, 13), n(13, 15));
}

/** Dernière URL retenue par asset. */
export type UrlCache = Map<number, string>;

/** Chaque rechargement du projet (SSE, toutes les 5 s pendant une génération) renvoie des URL présignées nouvellement
 *  signées : les lecteurs repartiraient de zéro. On garde l'URL déjà vue d'un asset tant qu'elle a été signée moins de
 *  30 min avant la nouvelle. */
export function stableUrls(cache: UrlCache, assets: Asset[]): Asset[] {
  return assets.map((a) => {
    const known = cache.get(a.id);
    if (known !== undefined && signedAt(a.url) - signedAt(known) < URL_REUSE_MS)
      return known === a.url ? a : { ...a, url: known };
    cache.set(a.id, a.url);
    return a;
  });
}

/** Infobulle d'une variante importée : son nom de fichier d'origine (nettoyé par le serveur, affiché seulement). */
export function importedTitle(asset: Pick<Asset, "original_name">): string | undefined {
  return asset.original_name ? `Importée : ${asset.original_name}` : undefined;
}

export interface Activity {
  step: StepName;
  /** L'étape elle-même (début de génération, avancement) : de quoi afficher le temps écoulé. */
  source: Step;
  /** Libellé de l'étape (« Clips »). */
  label: string;
  /** Ce qui est en cours : « scène 3 », « 2 scènes sur 8 », sinon « en cours ». */
  detail: string;
  /** Scène visée quand le lancement ne concerne qu'elle. */
  sceneId: number | null;
}

/** Générations en cours, une par étape qui tourne : de quoi dire, où que l'on soit dans l'éditeur, ce qui travaille. */
export function activities(steps: Step[], scenes: Pick<Scene, "id" | "position">[]): Activity[] {
  return steps
    .filter((s) => s.status === "running")
    .map((s) => {
      const target = scenes.find((sc) => sc.id === s.target_scene);
      return { step: s.name, source: s, label: STEP_LABELS[s.name], detail: activityDetail(s, scenes), sceneId: target?.id ?? null };
    });
}

/** Ce que l'étape en cours produit : « scène 3 », « 2 scènes sur 8 », sinon « en cours ». */
export function activityDetail(step: Pick<Step, "target_scene" | "progress">, scenes: Pick<Scene, "id" | "position">[]): string {
  const target = scenes.find((sc) => sc.id === step.target_scene);
  if (target) return `scène ${target.position}`;
  if (step.progress) return `${step.progress.done} scène${step.progress.done > 1 ? "s" : ""} sur ${step.progress.total}`;
  return "en cours";
}

/**
 * Temps d'une génération en cours : secondes écoulées depuis son lancement et secondes restantes (`null` si on ne peut
 * pas l'estimer). Dès qu'une scène est prête, le rythme mesuré remplace l'estimation du modèle (`unitSeconds`, durée
 * d'une scène) ; sans estimation ni scène prête, rien n'est promis. `remaining` à 0 : plus long que prévu.
 */
export function generationTiming(
  step: Pick<Step, "running_since" | "progress">,
  nowMs: number,
  unitSeconds: number | null,
): { elapsed: number; remaining: number | null } | null {
  if (!step.running_since) return null;
  const elapsed = Math.max(0, (nowMs - Date.parse(step.running_since)) / 1000);
  const { done = 0, total = 1 } = step.progress ?? {};
  if (done > 0) return { elapsed, remaining: Math.max(0, (total - done) * (elapsed / done)) };
  if (unitSeconds === null) return { elapsed, remaining: null };
  return { elapsed, remaining: Math.max(0, total * unitSeconds - elapsed) };
}

/** Générations en attente par projet (miroir de `MAX_QUEUED`, `app/services/queue_runs.py`). */
export const QUEUE_MAX = 5;

export const QUEUE_LABEL = "Mettre en file";
export const QUEUE_HINT = "Démarre dès que la génération en cours est terminée";

/** Une génération en file : « Clips, scène 7 », sans scène pour toutes. */
export function queueLabel(item: QueuedRun, scenes: Pick<Scene, "id" | "position">[]): string {
  const scene = scenes.find((s) => s.id === item.scene_id);
  return scene ? `${STEP_LABELS[item.step]}, scène ${scene.position}` : STEP_LABELS[item.step];
}

/** Pourquoi les boutons sont grisés : la génération en cours (ou, à défaut, l'action en attente), sinon `null`. */
export function busyReason(running: Activity[], busy: boolean): string | null {
  if (running.length > 0) return `En cours : ${running.map((a) => `${a.label}, ${a.detail}`).join(" ; ")}`;
  return busy ? "Action en cours" : null;
}

/** Images d'entrée d'un clip au plus, la principale comprise (miroir de `MAX_KONTEXT_IMAGES`, `services/story.py`). */
export const MAX_SCENE_IMAGES = 2;

/** Images envoyées après un clic sur `id` : retirée si elle y était, sinon ajoutée ; au-delà de `MAX_SCENE_IMAGES`, les plus
 *  anciennes sont retirées pour que la case cochée reste cochée. La première est l'image principale. */
export function toggled(ids: string[], id: string): string[] {
  if (ids.includes(id)) return ids.filter((i) => i !== id);
  return [...ids, id].slice(-MAX_SCENE_IMAGES);
}

/** Raison pour laquelle le clip d'une scène enchaînée ne peut pas être (re)généré seul : il part de la dernière image du
 *  clip précédent, qui n'existe pas encore. `null` : rien ne bloque. */
export function chainBlockedReason(scenes: Pick<Scene, "position" | "continuity" | "selected_clip_asset_id">[], scene: Pick<Scene, "position" | "continuity">): string | null {
  if (scene.continuity !== "continue") return null;
  const previous = scenes.find((s) => s.position === scene.position - 1);
  return previous && previous.selected_clip_asset_id === null
    ? `Générez d'abord le clip de la scène ${previous.position} : celle-ci part de sa dernière image.`
    : null;
}
