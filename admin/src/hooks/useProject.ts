import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, useApi, type ProjectDetail, type ProjectPatch, type StepPatch } from "../api";
import { useEvents } from "../events";
import { requestNotificationPermission } from "./useCompletionAlert";
import type { StepName } from "../steps";

const RUNNING_REFRESH_MS = 5000;

const formOf = (fields: Record<string, string | Blob>) => {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  return form;
};

/** Où s'affiche l'erreur d'une action : le panneau d'une étape, ou l'en-tête de l'éditeur (`studio`). */
export type ActionScope = StepName | "studio";

export interface RunOptions {
  /** Fusionnés dans les paramètres enregistrés de l'étape avant le lancement (`PATCH` s'ils changent ; étape reference : envoyés avec la demande). */
  params?: Record<string, unknown>;
  /** Valables pour ce lancement seulement, non enregistrés (provider/modèle d'une variante de clip) ; `resume` :
   *  reprise d'une étape par scène en échec ; `only_missing` : seulement les scènes sans média ; `visual_prompt` : nouveau prompt, enregistré sur la scène ; `instruction` : consigne de l'utilisateur pour le script ; `reference_id` : un seul élément de référence à (re)générer. */
  overrides?: { provider?: string; model?: string; resume?: boolean; only_missing?: boolean; visual_prompt?: string; instruction?: string; reference_id?: string; start_image?: string };
}

/**
 * Projet affiché dans l'éditeur et toutes ses mutations. Rechargé à chaque événement SSE du projet,
 * après chaque action (même en échec : un `503` passe l'étape en `failed`) et toutes les 5 s tant qu'une étape
 * tourne (filet si un événement de fin est perdu, ex. flux SSE coupé).
 * Les actions renvoient `true` en cas de succès ; l'erreur éventuelle est exposée dans `actionError`, rattachée à
 * l'étape dont le panneau l'affiche (le brief du projet s'édite dans l'étape Idée), ou à l'en-tête (`studio` : titre,
 * arrêt de l'autopilot).
 */
export function useProject(id: number) {
  const base = `/projects/${id}`;
  const { data: project, error, reload } = useApi<ProjectDetail>(base);
  const [busy, setBusy] = useState(false);
  // Garde synchrone : deux clics dans le même tick (avant le rendu qui désactive les boutons) n'envoient qu'une requête.
  const inFlight = useRef(false);
  const [actionError, setActionError] = useState<{ scope: ActionScope; message: string } | null>(null);

  useEvents((e) => {
    if (e.project_id === id) reload();
  });

  const running = project?.steps.some((s) => s.status === "running") ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(reload, RUNNING_REFRESH_MS);
    return () => clearInterval(timer);
  }, [running, reload]);

  /** Requête sur le projet : un FormData (envoi de fichier) part tel quel ; le reste en JSON. */
  const send = useCallback(
    <T,>(path: string, method: string, body?: unknown) =>
      api<T>(`${base}${path}`, { method, body: body === undefined || body instanceof FormData ? body : JSON.stringify(body) }),
    [base],
  );

  /** Exécute une action (une ou plusieurs requêtes), puis recharge le projet. */
  const perform = useCallback(
    async (scope: ActionScope, task: () => Promise<unknown>): Promise<boolean> => {
      if (inFlight.current) return false;
      inFlight.current = true;
      setBusy(true);
      setActionError(null);
      try {
        await task();
        return true;
      } catch (err) {
        setActionError({ scope, message: errorMessage(err) });
        return false;
      } finally {
        inFlight.current = false;
        setBusy(false);
        reload();
      }
    },
    [reload],
  );

  const act = useCallback(
    (scope: ActionScope, path: string, method: string, body?: unknown) => perform(scope, () => send(path, method, body)),
    [perform, send],
  );

  /** Arrête la génération en cours de l'étape : l'étape passe en échec « Arrêtée par l'utilisateur », le produit est gardé. */
  const cancel = useCallback((step: StepName) => act(step, `/steps/${step}/cancel`, "POST"), [act]);

  /** Retire une génération de la file d'attente avant son départ. */
  const unqueue = useCallback((id: number) => act("studio", `/queue/${id}`, "DELETE"), [act]);

  const patch = useCallback((step: StepName, body: StepPatch) => act(step, `/steps/${step}`, "PATCH", body), [act]);

  /** Lance l'étape (ou une seule scène `sceneId`). */
  const run = useCallback(
    async (step: StepName, sceneId?: number, { params, overrides }: RunOptions = {}) => {
      requestNotificationPermission();
      // Les paramètres de la référence partent avec la demande : appliqués au démarrage, même si elle attend en file
      // (le PATCH est refusé pendant que l'étape tourne).
      if (step === "reference") return act(step, `/steps/${step}/run`, "POST", { scene_id: sceneId, params, ...overrides });
      const current = project?.steps.find((s) => s.name === step)?.params ?? {};
      // Un champ texte vide équivaut à un paramètre absent : pas de PATCH inutile.
      const changed = params && Object.entries(params).some(([k, v]) => (current[k] ?? "") !== v);
      if (changed && !(await patch(step, { params: { ...current, ...params } }))) return false;
      return act(step, `/steps/${step}/run`, "POST", { scene_id: sceneId, ...overrides });
    },
    [act, patch, project],
  );

  return {
    project,
    loadError: error,
    refresh: reload,
    busy,
    actionError,
    run,
    cancel,
    unqueue,
    patch,
    approve: (step: StepName) => act(step, `/steps/${step}/approve`, "POST"),
    reorderScenes: (sceneIds: number[]) => act("studio", "/scenes/reorder", "POST", { scene_ids: sceneIds }),
    selectClip: (sceneId: number, assetId: number) =>
      act("clips", `/scenes/${sceneId}/select-clip`, "POST", { asset_id: assetId }),
    addReference: (name: string, prompt: string, storyId?: string) =>
      act("clips", "/references", "POST", { name, prompt, story_id: storyId }),
    setVoiceText: (sceneId: number, voiceText: string) =>
      act("voice", `/scenes/${sceneId}/voice-text`, "PUT", { voice_text: voiceText }),
    setSceneReference: (sceneId: number, reference: string, elements?: string[]) =>
      act("clips", `/scenes/${sceneId}/reference`, "PUT", { reference, elements }),
    setSceneContinuity: (sceneId: number, continuity: "cut" | "continue") =>
      act("clips", `/scenes/${sceneId}/continuity`, "PUT", { continuity }),
    setSceneLipsync: (sceneId: number, lipsync: boolean) =>
      act("clips", `/scenes/${sceneId}/lipsync`, "PUT", { lipsync }),
    deleteAsset: (assetId: number) => act("clips", `/assets/${assetId}`, "DELETE"),
    uploadClip: (sceneId: number, file: File, retouches?: number) =>
      act("clips", `/scenes/${sceneId}/upload-clip`, "POST", formOf({ file, ...(retouches ? { retouches: String(retouches) } : {}) })),
    /** Voix enregistrée de la scène (langue que la synthèse ne parle pas, voix réelle). */
    uploadVoice: (sceneId: number, file: File) => act("voice", `/scenes/${sceneId}/upload-voice`, "POST", formOf({ file })),
    uploadReference: (file: File, ref = "") => act("clips", "/reference/upload", "POST", formOf({ file, ref })),
    /** Nouvel élément créé à partir d'une image importée (description facultative). */
    addReferenceImage: (name: string, prompt: string, file: File) =>
      perform("clips", async () => {
        const element = await send<{ id: string }>("/references", "POST", { name, prompt });
        await send("/reference/upload", "POST", formOf({ file, ref: element.id }));
      }),
    /** Reprend une version précédente de l'image d'un élément (elle redevient celle des clips). */
    restoreReference: (assetId: number) => act("clips", `/reference/${assetId}/restore`, "POST"),
    updateProject: (body: ProjectPatch) => act("idea", "", "PATCH", body),
    setLipsync: (lipsync: boolean) => act("clips", "", "PATCH", { lipsync }),
    rename: (title: string) => act("studio", "", "PATCH", { title }),
    /** Génère (ou régénère) le plan : idée puis script, sans lancer les clips. */
    generatePlan: () => act("studio", "/plan/generate", "POST"),
    stopAutopilot: () => act("studio", "/autopilot", "DELETE"),
  };
}

export type Flow = ReturnType<typeof useProject>;
