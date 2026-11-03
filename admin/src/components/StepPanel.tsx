import { useId, type ReactNode } from "react";
import type { ProjectDetail, Scene } from "../api";
import type { Flow } from "../hooks/useProject";
import { activityDetail, QUEUE_HINT, QUEUE_LABEL } from "../studio";
import {
  affectedDownstream,
  availableActions,
  hasResult,
  resumeInfo,
  STEP_LABELS,
  STOPPED_BY_USER,
  statusLabel,
  type Step,
  type StepName,
} from "../steps";
import { priceLabel } from "../credits";
import { usePrice } from "../hooks/usePrice";
import GenerationTiming from "./GenerationTiming";
import PriceNote from "./PriceNote";
import { StopIcon } from "./icons";
import { useConfirm } from "../hooks/useConfirm";

const REGENERATE_ALL_HINT = "Refait toutes les scènes (nouveaux appels payants)";
const STALE_HINT = "Une étape précédente a changé depuis ce résultat : régénérez-le, ou validez-le tel quel s'il convient toujours.";

/** Ce que chaque panneau d'étape reçoit de l'éditeur. */
export interface PanelProps {
  flow: Flow;
  project: ProjectDetail;
  step: Step;
  previousApproved: boolean;
  /** Une action est en cours, l'étape ou une étape en aval tourne : boutons et enregistrements désactivés. */
  locked: boolean;
  /** Une demande de génération ne peut pas partir tout de suite : une action est en cours ou la file est pleine. */
  runLocked: boolean;
  /** La génération demandée attend son tour (l'étape ou une étape qui en dépend tourne) : « Mettre en file ». */
  queueing: boolean;
  /** Étapes en aval en cours de génération (l'API refuse alors d'éditer ou de relancer cette étape). */
  downstreamRunning: StepName[];
  /** Scène sélectionnée dans la timeline (`null` sans script). */
  scene: Scene | null;
  /** Ouvert depuis « Régénérer le clip » : l'étape Clips affiche d'emblée le volet du prompt de la scène. */
  promptOpen: boolean;
}

interface StepPanelProps extends PanelProps {
  /** Libellé du bouton de génération (défaut : « Générer », puis « Régénérer »). */
  runLabel?: string;
  /** Options du lancement qui changent son prix (ex. modèle vidéo choisi), pour le prix affiché sur les boutons. */
  priceBody?: Record<string, unknown>;
  /** Génération spécifique (ex. avec paramètres) ; défaut : lancer l'étape. */
  onRun?: () => void;
  /** Reprise d'une étape par scène en échec (ne génère que les scènes manquantes) ; défaut : sans paramètres. */
  onResume?: () => void;
  /** Relance de la seule scène dont la régénération a échoué (`step.target_scene`) ; défaut : sans paramètres. */
  onRetryScene?: (sceneId: number) => void;
  approveLabel?: string;
  /** Raison pour laquelle la validation est bloquée (affichée, bouton désactivé). */
  approveBlocked?: string;
  /** Raison pour laquelle la génération est bloquée (affichée, bouton désactivé), lien éventuel compris. */
  runBlocked?: ReactNode;
  /** Masque la génération (étape validée dont le résultat ne se rejoue plus). */
  hideRun?: boolean;
  /** Précise, dans la confirmation avant de remplacer un résultat existant, ce qui sera perdu. */
  confirmRun?: string;
  /** Actions propres au panneau, avant « Générer » et « Valider ». */
  extraActions?: ReactNode;
  children?: ReactNode;
}

/** Cadre commun d'une étape : en-tête, bandeau d'état, contenu propre au panneau, actions. */
export default function StepPanel({
  flow,
  project,
  step,
  previousApproved,
  locked,
  runLocked,
  queueing,
  downstreamRunning,
  runLabel,
  priceBody = {},
  onRun = () => flow.run(step.name),
  onResume = () => flow.run(step.name, undefined, { overrides: { resume: true } }),
  onRetryScene = (sceneId) => flow.run(step.name, sceneId),
  approveLabel = "Valider",
  approveBlocked,
  runBlocked,
  confirmRun,
  hideRun,
  extraActions,
  children,
}: StepPanelProps) {
  const titleId = useId();
  const { canRun, canApprove, showRetry, stale } = availableActions(step, previousApproved);
  const running = step.status === "running";
  const { confirm, dialog } = useConfirm();
  const label = runLabel ?? (hasResult(step) ? "Régénérer" : "Générer");
  const requestRun = () => {
    if (!hasResult(step)) return onRun();
    const redo = affectedDownstream(project.steps, step.name).map((n) => STEP_LABELS[n]);
    const message = [
      confirmRun ?? "Le résultat actuel sera remplacé.",
      redo.length > 0 && `À refaire ensuite : ${redo.join(", ")}.`,
    ];
    confirm({ title: `${label} ?`, message: message.filter(Boolean).join(" "), confirmLabel: label, onConfirm: onRun });
  };
  const requestStop = () =>
    confirm({
      title: "Arrêter la génération ?",
      message: "Ce qui est en cours est abandonné ; les éléments déjà générés restent disponibles.",
      confirmLabel: "Arrêter",
      onConfirm: () => flow.cancel(step.name),
    });
  const error = flow.actionError?.scope === step.name ? flow.actionError.message : null;
  const showRun = canRun && !showRetry && !hideRun;
  const resume = step.resume ? resumeInfo(step.resume) : null;
  const failedScene = step.status === "failed" ? project.scenes.find((s) => s.id === step.target_scene) : undefined;
  const stopped = step.error === STOPPED_BY_USER;
  const retrying = step.status === "failed" && canRun && showRetry;
  const runPrice = usePrice(project.id, step.name, showRun || retrying ? priceBody : null, step.status);
  const resumePrice = usePrice(project.id, step.name, retrying && !failedScene && resume ? { ...priceBody, resume: true } : null, step.status);
  const scenePrice = usePrice(project.id, step.name, retrying && failedScene ? { ...priceBody, scene_id: failedScene.id } : null, step.status);
  const hasFooter = Boolean(error || extraActions || showRun || canApprove);

  return (
    <section className={`step-panel st-${step.status}`} aria-labelledby={titleId}>
      <header className="step-panel-head">
        <h2 id={titleId}>{STEP_LABELS[step.name]}</h2>
        <span className="status-badge" title={stale ? STALE_HINT : undefined}>
          {statusLabel(step)}
        </span>
      </header>

      {running && (
        <div className="generation" role="status">
          <span className="spinner" aria-hidden />
          <div className="generation-text">
            <strong>{activityDetail(step, project.scenes)}</strong>
            <GenerationTiming step={step} />
          </div>
          <button className="btn btn-small btn-ghost" onClick={requestStop} disabled={flow.busy}>
            <StopIcon /> Arrêter
          </button>
          <div
            className={step.progress && !step.target_scene ? "generation-bar" : "generation-bar is-indeterminate"}
            aria-hidden
          >
            <span style={step.progress && !step.target_scene ? { width: `${(step.progress.done / step.progress.total) * 100}%` } : undefined} />
          </div>
        </div>
      )}
      {downstreamRunning.length > 0 && (
        <p className="notice" role="status">
          En cours en aval : {downstreamRunning.map((n) => STEP_LABELS[n]).join(", ")}
        </p>
      )}
      {step.status === "failed" && (
        <div className="notice" role="alert">
          <p>
            <strong>{stopped ? "Génération arrêtée." : "La génération a échoué."}</strong> {!stopped && step.error}
          </p>
          {showRetry && runBlocked && <p className="muted">{runBlocked}</p>}
          {showRetry && failedScene && (
            <>
              <button
                className="btn btn-primary"
                onClick={() => onRetryScene(failedScene.id)}
                disabled={runLocked || Boolean(runBlocked)}
                title="Ne refait que cette scène, les autres ne sont pas touchées"
              >
                {priceLabel(`Relancer la scène ${failedScene.position}`, scenePrice)}
              </button>
              <PriceNote quote={scenePrice} />
              <button className="btn" onClick={requestRun} disabled={runLocked || Boolean(runBlocked)} title={REGENERATE_ALL_HINT}>
                Tout régénérer
              </button>
            </>
          )}
          {showRetry && !failedScene && resume && (
            <>
              <p className="muted">{resume.text}</p>
              <button
                className="btn btn-primary"
                onClick={onResume}
                disabled={runLocked || Boolean(runBlocked)}
                title="Ne génère que les scènes manquantes"
              >
                {priceLabel(`Reprendre (${resume.remaining} restante${resume.remaining > 1 ? "s" : ""})`, resumePrice)}
              </button>
              <PriceNote quote={resumePrice} />
              <button className="btn" onClick={requestRun} disabled={runLocked || Boolean(runBlocked)} title={REGENERATE_ALL_HINT}>
                Tout régénérer
              </button>
            </>
          )}
          {showRetry && !failedScene && !resume && (
            <>
              <button className="btn" onClick={requestRun} disabled={runLocked || Boolean(runBlocked)}>
                {priceLabel("Relancer", runPrice)}
              </button>
              <PriceNote quote={runPrice} />
            </>
          )}
        </div>
      )}

      <div className="step-panel-body">{children}</div>

      {hasFooter && (
        <footer className="step-panel-actions">
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {canApprove && approveBlocked && <p className="muted">{approveBlocked}</p>}
          {showRun && runBlocked && <p className="muted">{runBlocked}</p>}
          {showRun && <PriceNote quote={runPrice} />}
          <div className="step-panel-buttons">
            {extraActions}
            {showRun && (
              // Action principale tant que l'étape n'a jamais été lancée ; ensuite, « Valider » prime.
              <button
                className={step.status === "pending" ? "btn btn-primary" : "btn"}
                onClick={requestRun}
                disabled={runLocked || Boolean(runBlocked)}
                title={queueing ? QUEUE_HINT : undefined}
              >
                {queueing ? QUEUE_LABEL : priceLabel(label, runPrice)}
              </button>
            )}
            {canApprove && (
              <button
                className="btn btn-primary"
                onClick={() => flow.approve(step.name)}
                disabled={locked || Boolean(approveBlocked)}
              >
                {approveLabel}
              </button>
            )}
          </div>
        </footer>
      )}
      {dialog}
    </section>
  );
}
