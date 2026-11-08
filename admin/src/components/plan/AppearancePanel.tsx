import { useApi, type ProjectDetail, type ProviderModels, type StyleOption } from "../../api";
import { choiceKey, imageChoice, imageOptions } from "../../models";
import type { usePlanDraft } from "../../hooks/usePlanDraft";
import AssistField from "../AssistField";
import CostSummary from "../CostSummary";
import TextArea from "../TextArea";
import { t } from "../../i18n";

interface Props {
  project: ProjectDetail;
  bible: ReturnType<typeof usePlanDraft>["bible"];
  locked: boolean;
  /** Le plan a des modifications non enregistrées (l'assistant le signale). */
  dirty: boolean;
}

/** Panneau Apparence de l'écran Plan : fiche visuelle (éditable, enregistrée avec le plan), style du projet, modèle des
 *  images de référence et dépense de la vidéo. */
export default function AppearancePanel({ project, bible, locked, dirty }: Props) {
  const styles = useApi<StyleOption[]>("/styles").data;
  const models = useApi<ProviderModels>("/providers/models").data;
  const imageDefault = useApi<Record<string, string>>("/settings/editor").data?.image_provider ?? "gemini";
  const params = project.steps.find((s) => s.name === "reference")?.params ?? {};
  const choice = imageChoice(
    models?.image,
    { provider: params.provider as string | undefined, model: params.model as string | undefined },
    imageDefault,
  );
  const imageModel = imageOptions(models?.image, choice).find((o) => o.value === choiceKey(choice))?.label;
  const style = styles?.find((s) => s.id === project.style)?.label ?? (project.style || "Aucun");

  return (
    <aside className="appearance" aria-labelledby="appearance-title">
      <h2 id="appearance-title">{t("Apparence")}</h2>
      <AssistField
        label={t("Fiche visuelle (personnages, marques, décor, style)")}
        kind="bible"
        value={bible.value}
        onChange={bible.set}
        context={{ projectId: project.id }}
        scope="fiche visuelle"
        locked={locked}
        unsaved={dirty}
      >
        {(f) => <TextArea {...f} className="input" rows={6} value={bible.value} onChange={(e) => bible.set(e.target.value)} />}
      </AssistField>
      <dl className="appearance-facts">
        <div>
          <dt>{t("Style")}</dt>
          <dd>{style}</dd>
        </div>
        <div>
          <dt>{t("Images de référence")}</dt>
          <dd>{imageModel ?? choice.model}</dd>
        </div>
      </dl>
      <CostSummary project={project} />
    </aside>
  );
}
