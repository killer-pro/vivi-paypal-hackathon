import { useRef, useState } from "react";
import { castOf } from "../../casting";
import { referenceElements, useApi, type Asset, type Estimate, type ProviderModels } from "../../api";
import { priceLabel } from "../../credits";
import { usd } from "../../format";
import { launchBlocked, pickable, START_IMAGE_LABELS, totalEstimate, type Choice } from "../../models";
import { availableActions, hasResult, missingScenes } from "../../steps";
import { chainBlockedReason, importedTitle, MAX_SCENE_IMAGES, QUEUE_HINT, QUEUE_LABEL, toggled } from "../../studio";
import { usePrice } from "../../hooks/usePrice";
import CastStrip from "../CastStrip";
import { CheckIcon, TrashIcon } from "../icons";
import ModelCards from "../ModelCards";
import PriceNote from "../PriceNote";
import StepPanel, { type PanelProps } from "../StepPanel";
import { useConfirm } from "../../hooks/useConfirm";
import { Advanced, ConfirmDialog, Field } from "../ui";
import PromptEditor from "./PromptEditor";
import ReferenceSection from "./ReferenceSection";
import SceneFocus from "./SceneFocus";

/** Clips : image de référence (facultative), profil de génération dans Avancé, variantes, upload local, prompt IA. */
export default function ClipsPanel(props: PanelProps) {
  const { flow, project, step, previousApproved, locked, runLocked, scene, promptOpen: openAtStart } = props;
  const models = useApi<ProviderModels>("/providers/models");
  const settings = useApi<Record<string, string>>("/settings/editor");
  const [picked, setPicked] = useState<Choice | null>(null);
  // Générateur de l'image de départ choisi pour ce lancement : vide = réglage `start_image_provider`.
  const [pickedStart, setPickedStart] = useState<string | null>(null);
  const startImage = pickedStart ?? String(step.params.start_image ?? "");
  const startOverride = startImage ? { start_image: startImage } : {};
  const { confirm, dialog } = useConfirm();
  const cards = models.data?.video ?? [];
  // Choix enregistré de l'étape, sinon défaut des réglages : inconnu (`null`) tant que les réglages ne sont pas chargés.
  const provider = step.params.provider ?? settings.data?.default_video_provider;
  const model = step.params.model ?? settings.data?.default_video_model;
  const saved = picked ?? (provider && model ? { provider: String(provider), model: String(model) } : null);
  // Un choix enregistré indisponible ou inconnu (ex. l'ancien « workflow ») est ramené sur une carte lançable.
  const choice = saved && pickable(cards, saved);
  const loadError = models.error ?? (saved ? null : settings.error); // réglages inutiles si l'étape a son choix
  const runBlocked = launchBlocked(models.data?.video, loadError, choice);

  // Prompt retravaillé d'une scène, par id de scène ; à défaut, le prompt enregistré (qui suit le serveur).
  const [prompts, setPrompts] = useState<Record<number, string>>({});
  // Remonte l'éditeur de prompt (consigne et historique d'amélioration remis à zéro) après un envoi.
  const [sent, setSent] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refStep = project.steps.find((s) => s.name === "reference");
  const elements = referenceElements(project.steps);
  const cast = castOf(project);
  // Images envoyées avec le clip, la principale d'abord : la référence de la scène, puis ses autres éléments qui en ont une.
  const withClip = scene ? [scene.reference, ...scene.elements.map((x) => x.id)].filter((id, i, all) => id && all.indexOf(id) === i && elements.some((e) => e.id === id)) : [];
  const chainBlocked = scene ? chainBlockedReason(project.scenes, scene) : null;

  const card = choice ? cards.find((c) => c.provider === choice.provider && c.id === choice.model) : undefined;
  const promptDraft = scene ? (prompts[scene.id] ?? scene.visual_prompt) : "";
  const promptChanged = scene !== null && promptDraft.trim() !== scene.visual_prompt.trim();

  // Pas d'estimation sans choix lançable (modèles ou réglages pas encore chargés, modèle vide).
  const estimate = useApi<Estimate>(
    choice && !runBlocked ? `/projects/${project.id}/estimate?${new URLSearchParams({ ...choice })}` : null,
  );
  const { canRun } = availableActions(step, previousApproved);
  const launchable = previousApproved && !runBlocked;
  // Prix d'une seule scène (nouvelle variante) et des scènes sans clip, pour les boutons correspondants.
  const scenePrice = usePrice(project.id, "clips", launchable && scene ? { ...choice, ...startOverride, scene_id: scene.id } : null, step.status);
  const missingPrice = usePrice(project.id, "clips", launchable && canRun ? { ...choice, ...startOverride, only_missing: true } : null, step.status);
  const missing = project.scenes.filter((s) => s.selected_clip_asset_id === null).length;
  const withoutClip = missingScenes(project.scenes, project.assets, "clip").length;
  const variants = project.assets.filter((a) => a.kind === "clip" && a.scene_id === scene?.id);

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !scene) return;
    setUploading(true);
    try {
      await flow.uploadClip(scene.id, file);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    const targetId = deleteTarget.id;
    setDeleteTarget(null);
    await flow.deleteAsset(targetId);
  }

  async function handleGenerateClip() {
    if (!scene) return;
    const ok = await flow.run("clips", scene.id, {
      overrides: { ...choice, ...startOverride, visual_prompt: promptDraft.trim() },
    });
    if (ok) {
      setPrompts(({ [scene.id]: _sent, ...rest }) => rest);
      setSent((n) => n + 1);
    }
  }

  /** Résumé compact du modèle choisi, affiché en dehors du volet Avancé. */
  const modelSummary = card
    ? card.name
    : runBlocked
      ? "—"
      : "Chargement…";

  return (
    <StepPanel
      {...props}
      runLabel={hasResult(step) ? "Régénérer tous les clips" : "Générer les clips"}
      priceBody={{ ...choice, start_image: startImage || undefined }}
      onRun={() => flow.run("clips", undefined, { params: { ...choice, start_image: startImage } })}
      onResume={() => flow.run("clips", undefined, { params: { ...choice, start_image: startImage }, overrides: { resume: true } })}
      onRetryScene={(sceneId) => flow.run("clips", sceneId, { overrides: { ...choice, ...startOverride } })}
      confirmRun={`Toutes les scènes (${project.scenes.length}) vont être régénérées en « ${card?.name ?? choice?.model} » : ${project.scenes.length} générations, et les clips choisis seront remplacés par les nouveaux. Pour refaire une seule scène, utilisez « Régénérer le clip » sous la scène.`}
      approveBlocked={missing ? "Choisissez une variante pour chaque scène avant de valider." : undefined}
      runBlocked={runBlocked}
      extraActions={
        withoutClip > 0 &&
        step.status !== "pending" && (
          <button
            className="btn"
            onClick={() =>
              confirm({
                title: `Générer ${withoutClip} clip${withoutClip > 1 ? "s" : ""} ?`,
                message: `${withoutClip} génération${withoutClip > 1 ? "s" : ""} en « ${card?.name ?? choice?.model} ». Les clips existants ne sont pas touchés.`,
                confirmLabel: "Générer",
                onConfirm: () => flow.run("clips", undefined, { params: { ...choice, start_image: startImage }, overrides: { only_missing: true } }),
              })
            }
            disabled={!canRun || locked || Boolean(runBlocked)}
          >
            {priceLabel(`Générer les ${withoutClip} clip${withoutClip > 1 ? "s" : ""} manquant${withoutClip > 1 ? "s" : ""}`, missingPrice)}
          </button>
        )
      }
    >
      <CastStrip cast={cast} flow={flow} />
      {refStep && <ReferenceSection {...props} refStep={refStep} cast={cast} models={models} imageDefault={settings.data?.image_provider ?? "gemini"} />}

      {/* ── Profil de génération vidéo (dans Avancé) ── */}
      <Advanced>
        <p className="advanced-model-summary">
          Modèle vidéo : <strong>{modelSummary}</strong>
          {estimate.data && !runBlocked && (
            <span className="muted">
              {" "}— {card?.minutes_per_clip != null
                ? totalEstimate(card, project.scenes.length)
                : `≈ ${usd.format(estimate.data.cost_usd)} pour ${estimate.data.scene_count} scène${estimate.data.scene_count > 1 ? "s" : ""}`}
            </span>
          )}
        </p>
        <ModelCards
          cards={models.data?.video}
          error={models.error}
          value={choice}
          onChange={setPicked}
          label="Profil de génération, toutes les scènes"
        />
        {choice?.provider === "comfyui" && (
          <Field label="Image de départ des scènes avec images de référence">
            <select className="input" value={startImage} onChange={(e) => setPickedStart(e.target.value)}>
              <option value="">
                Selon la préférence ({START_IMAGE_LABELS[settings.data?.start_image_provider ?? "comfyui"]})
              </option>
              {Object.entries(START_IMAGE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        )}
      </Advanced>

      <SceneFocus scene={scene} count={project.scenes.length}>
        {scene && (
          <label className="scene-element" title="Sans la case, le clip part de l'image de référence de la scène">
            <input
              type="checkbox"
              checked={scene.continuity === "continue"}
              disabled={flow.busy || scene.position === 1}
              onChange={(e) => flow.setSceneContinuity(scene.id, e.target.checked ? "continue" : "cut")}
            />
            Enchaîner : la première image part de la dernière image de la scène précédente
          </label>
        )}
        {scene && elements.length > 0 && (
          <fieldset className="scene-elements" disabled={flow.busy}>
            <legend>Images envoyées avec le clip ({MAX_SCENE_IMAGES} au plus : en cocher une de plus retire la plus ancienne)</legend>
            {elements.map((e) => {
              const member = cast.find((m) => m.id === e.id);
              const image = member?.imageUrl;
              return (
                <label key={e.id} className="scene-element">
                  <input
                    type="checkbox"
                    checked={withClip.includes(e.id)}
                    onChange={() => {
                      // La principale reste parmi les éléments de la scène (comme à l'écriture du script) : son état est
                      // conservé et elle garde sa pastille.
                      const sent = toggled(withClip, e.id);
                      flow.setSceneReference(scene.id, sent[0] ?? "", sent);
                    }}
                  />
                  {image ? <img className="scene-element-thumb" src={image} alt="" /> : <span className="scene-element-thumb" />}
                  {member?.name ?? e.id}{image ? "" : " (image à générer)"}
                </label>
              );
            })}
          </fieldset>
        )}
        {scene && (
          <div className="variants-header">
            <span className="variants-count">
              {variants.length} variante{variants.length > 1 ? "s" : ""}
            </span>
            <label className="btn btn-small" title="Importer une vidéo locale comme variante pour cette scène">
              {uploading ? "Importation…" : "Importer une vidéo"}
              <input
                ref={fileInputRef}
                type="file"
                accept="video/*,.mp4,.mov,.webm,.mkv,.m4v"
                hidden
                disabled={locked || uploading}
                onChange={handleFileSelect}
              />
            </label>
          </div>
        )}

        {variants.length === 0 ? (
          <p className="empty-line">Aucun clip pour cette scène.</p>
        ) : (
          <div className="variants">
            {variants.map((clip) => {
              const chosen = clip.id === scene?.selected_clip_asset_id;
              const keyframe = project.assets.find((a) => a.kind === "keyframe" && a.meta.clip_asset_id === clip.id);
              return (
                <figure key={clip.id} className={chosen ? "variant is-chosen" : "variant"}>
                  <video
                    className="frame-9x16"
                    src={clip.url}
                    poster={keyframe?.url}
                    controls
                    muted
                    loop
                    playsInline
                    preload="metadata"
                  />
                  <figcaption>
                    <div className="variant-head">
                      <span className="variant-label">
                        Variante {clip.variant}
                        {clip.meta?.model === "upload" && <span className="variant-badge" title={importedTitle(clip)}> (importée)</span>}
                      </span>
                      <button
                        type="button"
                        className="btn btn-ghost btn-danger btn-icon btn-small"
                        title="Supprimer cette variante"
                        aria-label={`Supprimer la variante ${clip.variant}`}
                        onClick={() => setDeleteTarget(clip)}
                        disabled={locked}
                      >
                        <TrashIcon />
                      </button>
                    </div>
                    <div className="variant-select-row">
                      {chosen ? (
                        <span className="chosen-tag">
                          <CheckIcon /> Choisie
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-small btn-choose"
                          onClick={() => scene && flow.selectClip(scene.id, clip.id)}
                          disabled={locked}
                        >
                          Choisir
                        </button>
                      )}
                    </div>
                  </figcaption>
                </figure>
              );
            })}
          </div>
        )}

        {scene && (
          <div
            ref={(el) => {
              if (el && openAtStart) el.scrollIntoView({ block: "start", behavior: "smooth" });
            }}
          >
            <PromptEditor
              key={`${scene.id}:${sent}`}
              title={`Prompt visuel — Scène ${scene.position}`}
              fieldLabel="Description de la scène"
              placeholder="Sujet, action, caméra, lumière, style (en anglais)..."
              instructionPlaceholder='Ex. : "Change le décor, mets un personnage de teint noir", "Ambiance coucher de soleil"...'
              rows={4}
              value={promptDraft}
              original={scene.visual_prompt}
              onChange={(v) => setPrompts((prev) => ({ ...prev, [scene.id]: v }))}
              assist={{ kind: "visual_prompt", context: { projectId: project.id, sceneId: scene.id } }}
            >
              <div className="scene-generate-action">
                <button
                  className="btn btn-primary"
                  disabled={!previousApproved || runLocked || Boolean(runBlocked) || Boolean(chainBlocked) || !promptDraft.trim()}
                  onClick={handleGenerateClip}
                  title={step.status === "running" ? QUEUE_HINT : undefined}
                >
                  {step.status === "running"
                    ? QUEUE_LABEL
                    : priceLabel(promptChanged ? "Valider le prompt et régénérer le clip" : "Générer une nouvelle variante", scenePrice)}
                </button>
                <PriceNote quote={scenePrice} />
                {previousApproved && runBlocked && <p className="muted">{runBlocked}</p>}
                {chainBlocked && <p className="muted">{chainBlocked}</p>}
              </div>
            </PromptEditor>
          </div>
        )}

        {deleteTarget && (
          <ConfirmDialog
            title="Supprimer la variante"
            message={
              deleteTarget.id === scene?.selected_clip_asset_id
                ? `Cette variante (${deleteTarget.variant}) est actuellement sélectionnée pour la scène ${scene?.position}. La supprimer va sélectionner une autre variante disponible. Confirmer la suppression ?`
                : `Voulez-vous supprimer la variante ${deleteTarget.variant} de cette scène ? Cette action est irréversible.`
            }
            confirmLabel="Supprimer"
            onConfirm={handleConfirmDelete}
            onCancel={() => setDeleteTarget(null)}
          />
        )}
      </SceneFocus>
      {dialog}
    </StepPanel>
  );
}
