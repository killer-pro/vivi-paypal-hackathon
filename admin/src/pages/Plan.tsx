import type { FormEvent } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { BackIcon, StopIcon } from "../components/icons";
import AppearancePanel from "../components/plan/AppearancePanel";
import ChatPanel from "../components/plan/ChatPanel";
import PlanProgress from "../components/plan/PlanProgress";
import PlanView from "../components/plan/PlanView";
import StoryView from "../components/plan/StoryView";
import TitleField from "../components/TitleField";
import { ErrorState } from "../components/ui";
import { useApi } from "../api";
import { useConfirm } from "../hooks/useConfirm";
import { DirtyDraftsContext, useDirtyDrafts } from "../hooks/useDraft";
import { usePlanDraft } from "../hooks/usePlanDraft";
import { useStoryDraft } from "../hooks/useStoryDraft";
import { parseVoices } from "../settings";
import { useProject, type Flow } from "../hooks/useProject";
import { needsPlanScreen, planLocks, planPhase, storyNeedsApproval } from "../planChat";
import type { ProjectDetail } from "../api";
import "./Plan.css";

/** Route `/projects/:id/plan` : un changement de projet remonte l'écran (brouillons remis à zéro). */
export default function PlanPage() {
  const id = Number(useParams().id);
  return <Plan key={id} id={id} />;
}

function Plan({ id }: { id: number }) {
  const flow = useProject(id);
  const drafts = useDirtyDrafts();
  const { project } = flow;
  if (!project)
    return (
      <main className="center-screen">
        {flow.loadError ? (
          <ErrorState message={flow.loadError} onRetry={flow.refresh} />
        ) : (
          <p className="muted">Chargement…</p>
        )}
      </main>
    );
  // Plan validé : l'éditeur prend le relais (il renvoie ici tant que le plan ne l'est pas : pas de boucle).
  if (!needsPlanScreen(project.steps)) return <Navigate to={`/projects/${id}`} replace />;
  return (
    <DirtyDraftsContext.Provider value={drafts.report}>
      <PlanScreen flow={flow} project={project} />
    </DirtyDraftsContext.Provider>
  );
}

function PlanScreen({ flow, project }: { flow: Flow; project: ProjectDetail }) {
  const navigate = useNavigate();
  const script = project.steps.find((s) => s.name === "script")!;
  const draft = usePlanDraft(project, script);
  const story = project.steps.find((s) => s.name === "story")!;
  const storyDraft = useStoryDraft(story);
  const voices = parseVoices(useApi<Record<string, string>>("/settings/editor").data?.voice_catalog);
  const storyWarnings = Array.isArray(story.result?.warnings) ? (story.result.warnings as string[]) : [];
  const { confirm, dialog } = useConfirm();
  const phase = planPhase(project.steps, project.scenes.length);
  const { locked, running, saveBlocked } = planLocks(project.steps, flow.busy);
  const error = flow.actionError?.message;

  function save(e: FormEvent) {
    e.preventDefault();
    void draft.save(flow);
  }

  /** Coupe l'enchaînement puis arrête l'étape en cours : le plan repart de « Générer le plan ». */
  async function stop() {
    const active = project.steps.find((s) => s.status === "running");
    if (await flow.stopAutopilot()) if (active) await flow.cancel(active.name);
  }

  function saveStory(e: FormEvent) {
    e.preventDefault();
    void storyDraft.save(flow);
  }

  /** L'histoire relue est validée, puis les scènes sont écrites à partir d'elle. */
  async function writeScenes() {
    if (!storyNeedsApproval(project.steps) || (await flow.approve("story"))) await flow.run("script");
  }

  async function validate() {
    if (await flow.approve("script")) navigate(`/projects/${project.id}`);
  }

  return (
    <div className="plan">
      <header className="plan-head">
        <Link className="back" to="/" aria-label="Retour aux projets" title="Retour aux projets">
          <BackIcon />
        </Link>
        <TitleField title={project.title} onRename={flow.rename} locked={flow.busy} />
      </header>
      {error && (
        <p className="error plan-error" role="alert">
          {error}
        </p>
      )}
      {phase === "generating" && (
        <PlanProgress
          steps={project.steps}
          title="L'IA prépare votre plan"
          lead="Chaque étape part de la précédente ; vous pourrez tout relire et modifier."
        >
          <button
            className="btn"
            disabled={flow.busy}
            onClick={() =>
              confirm({
                title: "Arrêter le plan ?",
                message: "La génération du plan est abandonnée ; vous pourrez la relancer.",
                confirmLabel: "Arrêter",
                onConfirm: stop,
              })
            }
          >
            <StopIcon /> Arrêter
          </button>
        </PlanProgress>
      )}
      {(phase === "failed" || phase === "empty") && (
        <PlanProgress
          steps={project.steps}
          title={phase === "failed" ? "La génération du plan a échoué" : "Le plan n'est pas encore généré"}
          lead={
            phase === "failed"
              ? "Réessayer relance la génération depuis l'idée."
              : "L'IA écrit l'idée puis l'histoire ; vous relirez l'histoire avant qu'elle écrive les scènes."
          }
        >
          <button className="btn btn-primary" disabled={locked} onClick={() => flow.generatePlan()}>
            {phase === "failed" ? "Réessayer" : "Générer le plan"}
          </button>
        </PlanProgress>
      )}
      {phase === "story" && (
        <>
          <div className="plan-body plan-body-story">
            <StoryView
              draft={storyDraft}
              warnings={storyWarnings}
              locked={locked}
              voices={voices}
              targetS={project.target_duration_s}
              onSave={saveStory}
            />
          </div>
          <PlanFoot
            hint="L'histoire est validée, puis l'IA écrit une scène par beat."
            label="Écrire les scènes"
            blocked={locked}
            dirtyReason={storyDraft.dirty ? "Enregistrez ou annulez vos modifications avant d'écrire les scènes" : null}
            onClick={writeScenes}
          />
        </>
      )}
      {phase === "ready" && (
        <>
          <div className="plan-body">
            <PlanView project={project} flow={flow} draft={draft} locked={locked} saveBlocked={saveBlocked} onSave={save} />
            <AppearancePanel project={project} bible={draft.bible} locked={locked} dirty={draft.dirty} />
            <ChatPanel
              projectId={project.id}
              dirty={draft.dirty}
              running={running}
              onPlanChanged={flow.refresh}
            />
          </div>
          <PlanFoot
            hint="Relisez les scènes et le casting avant de lancer la génération."
            label="Valider le plan et générer"
            blocked={locked}
            dirtyReason={draft.dirty ? "Enregistrez ou annulez vos modifications avant de valider" : null}
            onClick={() =>
              confirm({
                title: "Valider le plan et générer ?",
                message:
                  "Le plan est figé. Les images du casting qui manquent encore sont lancées maintenant ; vous lancerez ensuite les clips, la voix, la musique et le montage depuis la page projet. Les générations payantes comptent dans le budget du projet.",
                confirmLabel: "Valider et générer",
                onConfirm: validate,
              })
            }
          />
        </>
      )}
      {dialog}
    </div>
  );
}

/** Barre d'action de l'écran Plan, commune à l'histoire (« Écrire les scènes ») et aux scènes (« Valider le plan et
 *  générer ») : ce qu'on relit à gauche, l'action principale à droite, grisée tant qu'un brouillon n'est pas enregistré. */
function PlanFoot({
  hint,
  label,
  blocked,
  dirtyReason,
  onClick,
}: {
  hint: string;
  label: string;
  blocked: boolean;
  dirtyReason: string | null;
  onClick: () => void;
}) {
  return (
    <footer className="plan-foot">
      <p className="muted">{hint}</p>
      <button className="btn btn-primary btn-large" disabled={blocked || dirtyReason !== null} title={dirtyReason ?? undefined} onClick={onClick}>
        {label}
      </button>
    </footer>
  );
}
