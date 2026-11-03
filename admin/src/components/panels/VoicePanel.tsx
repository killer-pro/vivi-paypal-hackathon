import { Link } from "react-router-dom";
import AudioPlayer from "../AudioPlayer";
import { latestAsset, useApi } from "../../api";
import { priceLabel } from "../../credits";
import { useDraft } from "../../hooks/useDraft";
import { usePrice } from "../../hooks/usePrice";
import { availableActions, hasResult, missingScenes } from "../../steps";
import { QUEUE_HINT, QUEUE_LABEL } from "../../studio";
import PriceNote from "../PriceNote";
import StepPanel, { type PanelProps } from "../StepPanel";
import { useConfirm } from "../../hooks/useConfirm";
import { parseVoices, voiceLabel, withCurrent } from "../../settings";
import { Field } from "../ui";
import SceneFocus from "./SceneFocus";
import VoiceTextEditor from "./VoiceTextEditor";

/** Voix off : choix de la voix (catalogue des réglages), texte, écoute et régénération de la scène sélectionnée. */
export default function VoicePanel(props: PanelProps) {
  const { flow, project, step, previousApproved, locked, runLocked, scene } = props;
  const { confirm, dialog } = useConfirm();
  const settings = useApi<Record<string, string>>("/settings/editor");
  const catalog = parseVoices(settings.data?.voice_catalog);
  const defaultVoice = settings.data?.default_voice_id ?? "";
  // "" : la voix par défaut des réglages, suivie telle quelle (pas d'identifiant figé dans l'étape).
  const voiceId = useDraft(String(step.params.voice_id ?? ""));
  const params = { params: { voice_id: voiceId.value } };
  const { canRun } = availableActions(step, previousApproved);
  const voice = scene && latestAsset(project.assets, "voice", scene.id);
  const withoutVoice = missingScenes(project.scenes, project.assets, "voice").length;
  // Prix d'une seule voix et des voix manquantes, pour les boutons correspondants.
  const scenePrice = usePrice(project.id, "voice", previousApproved && scene ? { scene_id: scene.id } : null, step.status);
  const missingPrice = usePrice(project.id, "voice", previousApproved && canRun ? { only_missing: true } : null, step.status);

  return (
    <StepPanel
      {...props}
      runLabel={hasResult(step) ? "Régénérer toutes les voix" : "Générer les voix"}
      onRun={() => flow.run("voice", undefined, params)}
      onResume={() => flow.run("voice", undefined, { ...params, overrides: { resume: true } })}
      confirmRun={`Les ${project.scenes.length} voix sont régénérées (appels payants) et remplacent les actuelles.`}
      extraActions={
        withoutVoice > 0 &&
        step.status !== "pending" && (
          <button
            className="btn"
            onClick={() =>
              confirm({
                title: `Générer ${withoutVoice} voix ?`,
                message: `${withoutVoice} appel${withoutVoice > 1 ? "s" : ""} à la voix de synthèse (payant selon votre abonnement). Les voix existantes ne sont pas touchées.`,
                confirmLabel: "Générer",
                onConfirm: () => flow.run("voice", undefined, { ...params, overrides: { only_missing: true } }),
              })
            }
            disabled={!canRun || locked}
          >
            {priceLabel(`Générer les ${withoutVoice} voix manquante${withoutVoice > 1 ? "s" : ""}`, missingPrice)}
          </button>
        )
      }
    >
      <Field label="Voix">
        <select className="input" value={voiceId.value} onChange={(e) => voiceId.set(e.target.value)}>
          <option value="">
            {defaultVoice ? `Voix par défaut (${voiceLabel(catalog, defaultVoice)})` : "Voix par défaut (non choisie)"}
          </option>
          {withCurrent(catalog.map((v) => v.id), voiceId.value).map((id) => (
            <option key={id} value={id}>
              {voiceLabel(catalog, id)}
            </option>
          ))}
        </select>
      </Field>
      {!defaultVoice && !catalog.length && (
        <p className="muted">
          Aucune voix au catalogue. <Link to="/providers">Ajouter des voix dans les Réglages</Link>
        </p>
      )}
      <SceneFocus scene={scene} count={project.scenes.length} hideText>
        {scene && (
          <VoiceTextEditor
            key={scene.id}
            flow={flow}
            scene={scene}
            projectId={project.id}
            locked={locked}
            hasVoice={!!voice}
          />
        )}
        {voice ? (
          <AudioPlayer src={voice.url} label={`Voix de la scène ${scene.position}`} />
        ) : (
          <p className="empty-line">Pas encore de voix pour cette scène.</p>
        )}
        {scene && (
          <div>
            <button
              className="btn"
              onClick={() => {
                const run = () => flow.run("voice", scene.id, params);
                if (!voice) return run();
                confirm({
                  title: "Régénérer cette voix ?",
                  message: `La voix de la scène ${scene.position} est régénérée (appel payant) et remplace l'actuelle.`,
                  confirmLabel: "Régénérer",
                  onConfirm: run,
                });
              }}
              disabled={!previousApproved || runLocked}
              title={step.status === "running" ? QUEUE_HINT : undefined}
            >
              {step.status === "running" ? QUEUE_LABEL : priceLabel(voice ? "Régénérer cette voix" : "Générer cette voix", scenePrice)}
            </button>
            <PriceNote quote={scenePrice} />
          </div>
        )}
      </SceneFocus>
      {dialog}
    </StepPanel>
  );
}
