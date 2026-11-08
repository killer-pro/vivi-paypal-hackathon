import { useCallback, useEffect, useRef, useState } from "react";
import { isPublicPath } from "./auth";
import type { ModelCard, ModelStatus } from "./models";
import type { Step, StepName, StepStatus } from "./steps";

export type { Step };

export class ApiError extends Error {
  status: number;
  detail: string;
  /** `detail` vient de la réponse JSON de l'API (et non du texte de statut HTTP). */
  fromApi: boolean;

  constructor(status: number, detail: string, fromApi = false) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.fromApi = fromApi;
  }
}

/** Appel JSON (ou FormData) vers `/api{path}` avec le cookie de session. Sur 401 (hors écrans de compte), renvoie vers la page de découverte (`/decouvrir`). */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: "include",
    // FormData (upload) : le navigateur fixe lui-même le Content-Type multipart avec sa frontière.
    headers: { ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...init.headers },
  });
  if (res.status === 401 && !isPublicPath(window.location.pathname)) window.location.assign("/decouvrir");
  if (!res.ok) {
    const detail = detailOf(await res.json().catch(() => null));
    throw new ApiError(res.status, detail ?? res.statusText, detail !== null);
  }
  const text = await res.text(); // 202/204 sans corps (ex. lancement d'étape)
  return (text ? JSON.parse(text) : undefined) as T;
}

/** Message à afficher : le `detail` de l'API (ex. 409, 503 « File d'attente indisponible »), ou « Serveur injoignable »
 *  (réseau, proxy sans backend, 5xx sans réponse JSON de l'API). */
export function errorMessage(err: unknown): string {
  return err instanceof ApiError && (err.status < 500 || err.fromApi) ? err.detail : "Serveur injoignable";
}

/**
 * Charge `path` au montage ; `reload` relance l'appel. Un 401 n'est pas une erreur affichée : `api` redirige.
 * Seule la réponse à la dernière requête est retenue : une réponse plus ancienne arrivée en retard est ignorée.
 * `path` null : aucun appel (requête pas encore possible), ni donnée ni erreur. `status` : code HTTP de l'échec affiché.
 */
export function useApi<T>(path: string | null): {
  data: T | undefined;
  error: string | null;
  status: number | null;
  reload: () => void;
} {
  const [state, setState] = useState<{ data?: T; error: string | null; status?: number | null }>({ error: null });
  const latest = useRef(0);

  const load = useCallback(() => {
    const request = ++latest.current;
    if (path === null) return;
    api<T>(path).then(
      (data) => {
        if (request === latest.current) setState({ data, error: null });
      },
      (err) => {
        if (request === latest.current && !(err instanceof ApiError && err.status === 401))
          setState((s) => ({ ...s, error: errorMessage(err), status: err instanceof ApiError ? err.status : null }));
      },
    );
  }, [path]);
  useEffect(load, [load]);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, error: null, status: null }));
    load();
  }, [load]);

  return path === null
    ? { data: undefined, error: null, status: null, reload }
    : { data: state.data, error: state.error, status: state.status ?? null, reload };
}

/** FastAPI renvoie `detail` en texte (HTTPException) ou en liste d'erreurs (validation 422). */
function detailOf(body: { detail?: unknown } | null): string | null {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(" ; ");
  return null;
}

export interface Project {
  id: number;
  title: string;
  status: string;
  /** Mode automatique : le backend enchaîne et valide les étapes seul. */
  autopilot: boolean;
  current_step: StepName | null;
  current_status: StepStatus | null;
  /** Dépense en dollars : admin seulement (nulle pour un client). */
  cost_usd: number | null;
  /** Crédits pris par le projet : client seulement (nul pour l'admin). */
  credits_spent: number | null;
  created_at: string;
}

/** Page d'une liste paginée : `total` compte toutes les entrées correspondantes, pas seulement la page. */
export interface Page<T> {
  items: T[];
  total: number;
}

/** Élément de `GET /projects` : vignette = dernier rendu, sinon clip choisi de la première scène. */
export interface ProjectCard extends Project {
  thumbnail_url: string | null;
  render_asset_id: number | null;
}

export interface Scene {
  id: number;
  position: number;
  voice_text: string;
  visual_prompt: string;
  duration_s: number;
  selected_clip_asset_id: number | null;
  /** Id d'un élément de référence du script dont l'image sert au clip (`""` : aucun). */
  reference: string;
  /** Éléments visibles dans la scène (`state` : leur état) : leurs images accompagnent la principale dans le clip. */
  elements: { id: string; state: string }[];
  /** `continue` : le clip part de la dernière image du clip de la scène précédente ; `cut` : de l'image de référence. */
  continuity: "cut" | "continue";
}

export interface Asset {
  id: number;
  scene_id: number | null;
  kind: "reference" | "clip" | "keyframe" | "voice" | "render"; // keyframe : image de départ d'un clip (`meta.clip_asset_id`)
  key: string;
  content_type: string;
  variant: number;
  meta: Record<string, unknown>;
  created_at: string;
  url: string;
  /** Nom du fichier importé (upload), nettoyé par le serveur : affiché seulement. `null` pour un asset généré. */
  original_name: string | null;
}

/** Génération demandée pendant qu'une autre bloquait l'étape, lancée dans l'ordre (file d'attente du projet). */
export interface QueuedRun {
  id: number;
  step: StepName;
  /** Scène visée, `null` pour toutes. */
  scene_id: number | null;
}

export interface ProjectDetail extends Project {
  theme: string;
  platform: string;
  target_duration_s: number;
  /** Style visuel (`""` : aucun). */
  style: string;
  metadata_json: Record<string, unknown>;
  /** Dépenses par étape (assistant IA sous `assist`), seules celles qui ont coûté : justifie `cost_usd`. */
  cost_by_step: Record<string, number> | null;
  /** Plafond par vidéo en dollars, 0 = sans limite ; admin seulement. */
  budget_usd: number | null;
  steps: Step[];
  queue: QueuedRun[];
  scenes: Scene[];
  assets: Asset[];
}

export type ProjectIn = Pick<ProjectDetail, "title" | "theme" | "platform" | "target_duration_s">;

/** Style visuel proposé à la création (`GET /styles`). */
export interface StyleOption {
  id: string;
  label: string;
}

export type ProjectPatch = Partial<ProjectIn>;

/** Corps de `PATCH /projects/{id}/steps/{name}`. */
export interface StepPatch {
  params?: Record<string, unknown>;
  result?: Record<string, unknown>;
  scenes?: (Pick<Scene, "voice_text" | "visual_prompt" | "duration_s"> & { id?: number })[];
}

/** Message du chat du plan ; `can_undo` : le dernier changement du plan fait par l'IA, annulable. */
export interface PlanMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  can_undo: boolean;
  created_at: string;
}

export interface MusicTrack {
  id: number;
  name: string;
  tags: string[];
  duration_s: number;
  url: string;
}

export interface ProviderModels {
  video: ModelCard[];
  image: ModelStatus[];
  llm: Record<string, string[]>;
}

export interface Estimate {
  provider: string;
  model: string;
  scene_count: number;
  /** Admin seulement (nul pour un client). */
  cost_usd: number | null;
}

/** Élément récurrent (personnage, produit) que le script a listé : son image de référence reste la même d'une scène à l'autre. */
export interface ReferenceElement {
  id: string;
  prompt: string;
}

/** Éléments de référence du script (liste vide pour un script sans élément ou d'avant les éléments). */
export function referenceElements(steps: Step[]): ReferenceElement[] {
  const list = steps.find((s) => s.name === "script")?.result?.references;
  return Array.isArray(list) ? (list as ReferenceElement[]) : [];
}

/** Élément de l'histoire qui n'est pas (encore) une référence : `prompt` est celui de son image, à défaut sa description. */
export interface StoryElement {
  id: string;
  name: string;
  prompt: string;
}

/** Éléments de l'histoire sans image de référence (accessoires au-delà du plafond, lieux), à promouvoir à la demande. */
export function storyElementsWithoutReference(steps: Step[]): StoryElement[] {
  const story = steps.find((s) => s.name === "story")?.result?.elements;
  if (!Array.isArray(story)) return [];
  const taken = new Set(referenceElements(steps).map((r) => r.id));
  return (story as { id: string; name?: string; prompt?: string; descriptor?: string }[])
    .filter((e) => !taken.has(e.id))
    .map((e) => ({ id: e.id, name: e.name || e.id, prompt: e.prompt || [e.name, e.descriptor].filter(Boolean).join(", ") }))
    .filter((e) => e.prompt);
}

/** Numéros des scènes qui prennent l'élément `ref` comme référence principale ou comme image secondaire. */
export function scenesUsing(scenes: Pick<Scene, "position" | "reference" | "elements">[], ref: string): number[] {
  return scenes.filter((s) => s.reference === ref || s.elements.some((e) => e.id === ref)).map((s) => s.position);
}

/** Dernière image de référence de l'élément `ref` (`""` : image du projet entier, sans élément). */
export function referenceImage(assets: Asset[], ref: string): Asset | undefined {
  return assets.findLast((a) => a.kind === "reference" && ((a.meta.ref as string | undefined) ?? "") === ref);
}

/** Dernier asset produit d'un type (pour une scène donnée, ou hors scène). */
export function latestAsset(assets: Asset[], kind: Asset["kind"], sceneId: number | null = null): Asset | undefined {
  return assets.findLast((a) => a.kind === kind && a.scene_id === sceneId);
}
