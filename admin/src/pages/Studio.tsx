import { useEffect, useMemo, useRef, useState, type ComponentType, type CSSProperties } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { queueMax, type Access } from "../access";
import { latestAsset, useApi, type MusicTrack, type ProjectDetail, type ProviderModels } from "../api";
import CostSummary from "../components/CostSummary";
import { UnitSecondsContext } from "../components/unitSeconds";
import { BackIcon, DownloadIcon, StopIcon } from "../components/icons";
import TitleField from "../components/TitleField";
import type { PanelProps } from "../components/StepPanel";
import ClipsPanel from "../components/panels/ClipsPanel";
import FinalPanel from "../components/panels/FinalPanel";
import IdeaPanel from "../components/panels/IdeaPanel";
import MontagePanel from "../components/panels/MontagePanel";
import MusicPanel from "../components/panels/MusicPanel";
import StoryPanel from "../components/panels/StoryPanel";
import ScriptPanel from "../components/panels/ScriptPanel";
import VoicePanel from "../components/panels/VoicePanel";
import ActivityBar from "../components/studio/ActivityBar";
import MobileTabs, { type Pane } from "../components/studio/MobileTabs";
import Pipeline from "../components/studio/Pipeline";
import Preview from "../components/studio/Preview";
import SceneList from "../components/studio/SceneList";
import Timeline from "../components/studio/Timeline";
import { ConfirmDialog, ErrorState } from "../components/ui";
import { useConfirm } from "../hooks/useConfirm";
import PanelEdge from "../components/studio/PanelEdge";
import { useCompletionAlert } from "../hooks/useCompletionAlert";
import { DirtyDraftsContext, useDirtyDrafts } from "../hooks/useDraft";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { usePanelLayout } from "../hooks/usePanelLayout";
import { useMediaDurations } from "../hooks/useMediaDurations";
import { usePlayer } from "../hooks/usePlayer";
import { musicVolume, sceneTiming } from "../montage";
import { useProject, type Flow } from "../hooks/useProject";
import { needsPlanScreen } from "../planChat";
import { currentStep, previousApproved, runningDownstream, type StepName } from "../steps";
import {
  activities,
  autopilotLabel,
  busyReason,
  exportBlockedReason,
  neighbourScene,
  reorderedIds,
  renderIsCurrent,
  shortcutFor,
  stableUrls,
  timeline,
  toolOf,
  toolStep,
  type UrlCache,
} from "../studio";
import "./Studio.css";
import { t } from "../i18n";

const PANELS: Record<StepName, ComponentType<PanelProps>> = {
  idea: IdeaPanel,
  story: StoryPanel,
  script: ScriptPanel,
  reference: ClipsPanel, // la référence est gérée directement dans ClipsPanel
  clips: ClipsPanel,
  voice: VoicePanel,
  music: MusicPanel,
  montage: MontagePanel,
  final: FinalPanel,
};

/** Route `/projects/:id` : un changement de projet remonte l'éditeur (état, brouillons et sélection remis à zéro). */
export default function StudioPage() {
  const id = Number(useParams().id);
  return <Studio key={id} id={id} />;
}

/** URL présignées stables d'un rechargement à l'autre (voir `stableUrls`). */
function useStableProject(project: ProjectDetail | undefined): ProjectDetail | undefined {
  const [cache] = useState<UrlCache>(() => new Map());
  return useMemo(() => project && { ...project, assets: stableUrls(cache, project.assets) }, [cache, project]);
}

/**
 * Éditeur plein cadre : en-tête (retour, titre, autopilot, export), frise des étapes, scènes, aperçu 9:16, panneau de
 * l'étape et timeline. Par défaut, le panneau suit l'étape courante ; la scène sélectionnée est partagée par l'aperçu, la
 * timeline et les panneaux qui travaillent scène par scène.
 */
function Studio({ id }: { id: number }) {
  const flow = useProject(id);
  const access = useApi<Access>("/access").data; // taille de la file : forfait du compte
  const project = useStableProject(flow.project);
  const [selected, setSelected] = useState<StepName | null>(null);
  const [sceneIndex, setSceneIndex] = useState(0);
  // Petit écran : un seul volet visible (voir MobileTabs) ; sans effet sur grand écran.
  const [pane, setPane] = useState<Pane>("preview");
  // Incrémenté par « Régénérer le clip » : remonte le panneau Clips avec le volet du prompt ouvert (0 : ouverture normale).
  const [repromptToken, setRepromptToken] = useState(0);
  const drafts = useDirtyDrafts();
  // Colonnes latérales réglables et repliables ; sur petit écran, les onglets prennent le relais.
  const { layout, resize, toggle, reset } = usePanelLayout();
  const compact = useMediaQuery("(max-width: 900px)");
  const railCollapsed = !compact && layout.rail.collapsed;
  const panelCollapsed = !compact && layout.panel.collapsed;
  const [pendingLeave, setPendingLeave] = useState<(() => void) | null>(null);
  const { confirm, dialog: confirmDialog } = useConfirm();
  const navigate = useNavigate();
  useCompletionAlert(flow.project?.title, flow.project?.steps);
  const tracks = useApi<MusicTrack[]>("/music");
  const models = useApi<ProviderModels>("/providers/models");

  const scenes = project?.scenes ?? [];
  // Durée de chaque scène : calée sur sa voix et son clip comme le montage (durée prévue au script tant qu'ils manquent).
  const assets = project?.assets ?? [];
  const media = scenes.map((s) => ({
    voice: latestAsset(assets, "voice", s.id),
    clip: assets.find((a) => a.id === s.selected_clip_asset_id),
  }));
  const durations = useMediaDurations(media.flatMap(({ voice, clip }) => [voice, clip].filter((a) => a !== undefined)));
  const timings = scenes.map((s, i) =>
    sceneTiming(durations.get(media[i].voice?.id ?? -1), durations.get(media[i].clip?.id ?? -1), s.duration_s),
  );
  const { blocks, total } = timeline(timings.map((t) => ({ duration_s: t.duration })));
  const index = Math.min(sceneIndex, scenes.length - 1);
  const scene = scenes[index] ?? null;
  const render = project && latestAsset(project.assets, "render");
  // Aperçu : le rendu seulement s'il est à jour ; après une modification de clip, le clip de la scène.
  const previewRender = project && renderIsCurrent(project.steps) ? render?.url : undefined;
  const clip = project?.assets.find((a) => a.id === scene?.selected_clip_asset_id);
  const voice = project && scene ? latestAsset(project.assets, "voice", scene.id) : undefined;
  const musicStep = project?.steps.find((s) => s.name === "music");
  const trackId = musicStep?.params.track_id ?? musicStep?.result?.track_id;
  const track = tracks.data?.find((t) => t.id === trackId);
  const player = usePlayer({
    render: previewRender,
    clip: clip?.url,
    voice: voice?.url,
    music: track?.url,
    musicVolume: musicVolume(musicStep?.params) / 100,
    blocks,
    timings,
    total,
    index,
    setIndex: setSceneIndex,
  });

  // Raccourcis : espace = lecture, ← → = scène voisine (hors champs de saisie, lecteurs et modales).
  const keys = useRef({ player, index, count: scenes.length });
  useEffect(() => {
    keys.current = { player, index, count: scenes.length };
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || el.closest("dialog")) return;
      const action = shortcutFor(e.key, { tag: el.tagName, role: el.getAttribute("role"), scene: "sceneBlock" in el.dataset });
      if (!action) return;
      e.preventDefault();
      const { player: p, index: i, count } = keys.current;
      if (action === "toggle") p.toggle();
      else p.select(neighbourScene(i, action === "next" ? 1 : -1, count));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /** Quitter l'étape affichée : confirmation d'abord si des modifications ne sont pas enregistrées. */
  const leave = (action: () => void) => (drafts.hasDirty() ? setPendingLeave(() => action) : action());

  if (project && needsPlanScreen(project.steps)) return <Navigate to={`/projects/${id}/plan`} replace />;
  if (!project)
    return (
      <main className="center-screen">
        {flow.loadError ? (
          <ErrorState message={flow.loadError} onRetry={flow.refresh} />
        ) : (
          <p className="muted">{t("Chargement…")}</p>
        )}
      </main>
    );

  const current = currentStep(project.steps);
  const rawName = selected ?? current;
  const name = rawName === "reference" ? "clips" : rawName;
  const tool = toolOf(name);
  const step = project.steps.find((s) => s.name === name)!;
  const Panel = PANELS[name];
  const downstreamRunning = runningDownstream(project.steps, name);
  const openStep = (s: StepName) => {
    setPane("step");
    setRepromptToken(0);
    if (s !== name) leave(() => setSelected(s));
  };
  const editClip = () => {
    setPane("step");
    if (name !== "clips") leave(() => setSelected("clips"));
    setRepromptToken((n) => n + 1);
  };
  // Après une validation, on suit de nouveau l'étape courante : le panneau passe à l'étape suivante.
  const advancing: Flow = {
    ...flow,
    approve: async (s) => {
      const ok = await flow.approve(s);
      if (ok && !drafts.hasDirty()) setSelected(null);
      return ok;
    },
  };
  const reorderLocked = flow.busy || ["clips", "voice", "montage"].some((n) => project.steps.find((s) => s.name === n)?.status === "running");
  const moveScene = async (delta: -1 | 1) => {
    const ids = reorderedIds(scenes.map((s) => s.id), index, delta);
    if (ids && (await flow.reorderScenes(ids))) setSceneIndex(index + delta);
  };
  const exportBlocked = exportBlockedReason(project.steps, !!render);
  const running = activities(project.steps, scenes);
  const headerError = flow.actionError?.scope === "studio" ? flow.actionError.message : null;
  const busyText = busyReason(running, flow.busy);
  // Durée estimée d'un clip du modèle choisi (ComfyUI seulement : un modèle payant n'a pas de durée annoncée).
  const unitSeconds = (stepName: StepName) => {
    if (stepName !== "clips") return null;
    const cards = models.data?.video ?? [];
    const { provider, model } = project.steps.find((s) => s.name === "clips")?.params ?? {};
    const card = cards.find((c) => c.provider === provider && c.id === model) ?? cards.find((c) => c.recommended);
    return card?.minutes_per_clip != null ? card.minutes_per_clip * 60 : null;
  };

  return (
    <UnitSecondsContext.Provider value={unitSeconds}>
    <div
      className={scenes.length > 0 ? "studio has-scenes" : "studio"}
      data-pane={pane}
      data-busy={busyText ? "" : undefined}
      style={
        {
          "--rail-w": `${railCollapsed ? 0 : layout.rail.width}px`,
          "--panel-w": `${panelCollapsed ? 0 : layout.panel.width}px`,
          "--busy-reason": busyText ? JSON.stringify(busyText) : undefined,
        } as CSSProperties
      }
    >
      <header className="studio-head">
        <Link
          className="back"
          to="/"
          aria-label={t("Retour aux projets")}
          title={t("Retour aux projets")}
          onClick={(e) => {
            e.preventDefault();
            leave(() => navigate("/"));
          }}
        >
          <BackIcon />
        </Link>
        <TitleField title={project.title} onRename={flow.rename} locked={flow.busy} />
        <CostSummary project={project} />
        <ActivityBar
          activities={running}
          busy={flow.busy}
          onShow={(a) => {
            if (a.sceneId !== null) player.select(scenes.findIndex((s) => s.id === a.sceneId));
            openStep(a.step);
          }}
          onStop={(a) =>
            confirm({
              title: t("Arrêter la génération ?"),
              message: t("« {label} » est abandonnée ; les éléments déjà générés restent disponibles.", { label: a.label }),
              confirmLabel: t("Arrêter"),
              onConfirm: () => flow.cancel(a.step),
            })
          }
          queue={project.queue}
          scenes={scenes}
          onUnqueue={flow.unqueue}
        />
        <div className="studio-actions">
          {project.autopilot && (
            <div className="autopilot" role="status">
              <span className="autopilot-dot" aria-hidden />
              <span className="autopilot-text">
                Génération automatique : <strong>{autopilotLabel(project)}</strong>
              </span>
              <button className="btn btn-small btn-ghost" onClick={flow.stopAutopilot} disabled={flow.busy}>
                <StopIcon /> {t("Arrêter")}
              </button>
            </div>
          )}
          {render && !exportBlocked ? (
            <a className="btn btn-primary" href={`/api/projects/${project.id}/assets/${render.id}/download`}>
              <DownloadIcon /> <span className="hide-narrow">{t("Exporter")}</span>
            </a>
          ) : (
            <button className="btn" disabled title={exportBlocked ?? undefined}>
              <DownloadIcon /> <span className="hide-narrow">{t("Exporter")}</span>
            </button>
          )}
        </div>
        {headerError && (
          <p className="error studio-error" role="alert">
            {headerError}
          </p>
        )}
      </header>

      <Pipeline
        steps={project.steps}
        selected={tool.id}
        onSelect={(t) => t.id !== tool.id && openStep(toolStep(t, current))}
      />

      {scenes.length > 0 && (
        <SceneList
          project={project}
          index={index}
          onSelect={(i) => {
            player.select(i);
            setPane("preview");
          }}
          onMove={moveScene}
          locked={reorderLocked}
          generating={running}
          collapsed={railCollapsed}
        >
          {!compact && (
            <PanelEdge
              id="rail"
              label={t("les scènes")}
              width={layout.rail.width}
              collapsed={railCollapsed}
              onResize={(w) => resize("rail", w)}
              onToggle={() => toggle("rail")}
              onReset={() => reset("rail")}
            />
          )}
        </SceneList>
      )}

      <aside className={panelCollapsed ? "studio-panel is-collapsed" : "studio-panel"} aria-label={t("Étape en cours")}>
        {!compact && (
            <PanelEdge
              id="panel"
              label={t("le panneau de l'étape")}
              width={layout.panel.width}
              collapsed={panelCollapsed}
              onResize={(w) => resize("panel", w)}
              onToggle={() => toggle("panel")}
              onReset={() => reset("panel")}
            />
          )}
        <div className="studio-panel-scroll" inert={panelCollapsed}>
        <DirtyDraftsContext.Provider value={drafts.report}>
          <Panel
            key={`${name}:${repromptToken}`}
            flow={advancing}
            project={project}
            step={step}
            previousApproved={previousApproved(project.steps, name)}
            locked={flow.busy || step.status === "running" || downstreamRunning.length > 0}
            runLocked={flow.busy || project.queue.length >= queueMax(access)}
            queueing={step.status === "running" || downstreamRunning.length > 0}
            downstreamRunning={downstreamRunning}
            scene={scene}
            promptOpen={repromptToken > 0}
          />
        </DirtyDraftsContext.Provider>
        </div>
      </aside>

      <Preview
        player={player}
        render={previewRender}
        clip={clip?.url}
        voice={voice?.url}
        music={track?.url}
        scene={scene}
        subtitles={project.steps.find((s) => s.name === "montage")?.params.subtitle_style !== "none"}
        total={total}
        onEditClip={editClip}
        onEditVoice={() => openStep("voice")}
      />

      <Timeline
        project={project}
        blocks={blocks}
        total={total}
        index={index}
        time={player.time}
        musicName={track?.name ?? null}
        onSelect={player.select}
        onSeek={player.seek}
        onFill={(s, i) => {
          player.select(i);
          openStep(s);
        }}
      />

      <MobileTabs pane={pane} onChange={setPane} sceneCount={scenes.length} />

      {pendingLeave && (
        <ConfirmDialog
          title={t("Modifications non enregistrées")}
          message={t("Les modifications de cette étape n'ont pas été enregistrées et seront perdues.")}
          confirmLabel={t("Quitter sans enregistrer")}
          onConfirm={() => {
            pendingLeave();
            setPendingLeave(null);
          }}
          onCancel={() => setPendingLeave(null)}
        />
      )}
      {confirmDialog}
    </div>
    </UnitSecondsContext.Provider>
  );
}
