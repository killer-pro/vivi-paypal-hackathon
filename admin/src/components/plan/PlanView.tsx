import type { FormEvent } from "react";
import type { ProjectDetail } from "../../api";
import { castOf } from "../../casting";
import type { usePlanDraft } from "../../hooks/usePlanDraft";
import type { Flow } from "../../hooks/useProject";
import CastStrip from "../CastStrip";
import SceneCard from "../SceneCard";
import { FormActions } from "../ui";
import { locale, t, tn } from "../../i18n";

interface Props {
  project: ProjectDetail;
  flow: Flow;
  draft: ReturnType<typeof usePlanDraft>;
  locked: boolean;
  /** Raison pour laquelle l'API refuserait l'enregistrement (images de référence en cours), sinon `null`. */
  saveBlocked: string | null;
  onSave: (e: FormEvent) => void;
}

/** Plan éditable : casting (images de référence, mises à jour en direct), puis scènes en cartes (repliables, dépliées
 *  par défaut), avec enregistrement du brouillon (fiche visuelle comprise, éditée dans le panneau Apparence). */
export default function PlanView({ project, flow, draft, locked, saveBlocked, onSave }: Props) {
  const { list, dirty, total, blank, ordered } = draft;
  const cast = castOf(project);
  return (
    <form className="form plan-view" onSubmit={onSave}>
      {cast.length > 0 && (
        <section className="plan-section" aria-labelledby="plan-cast">
          <h2 id="plan-cast">{t("Casting")}</h2>
          <CastStrip cast={cast} flow={flow} />
        </section>
      )}
      <section className="plan-section" aria-labelledby="plan-scenes">
        <div className="plan-section-head">
          <h2 id="plan-scenes">{t("Scènes")}</h2>
          <span className="muted">
            {tn(list.length, "{n} scène", "{n} scènes")}, {total.toLocaleString(locale)} s {t("sur")} {project.target_duration_s} s {t("visées")}
          </span>
        </div>
        <ol className="scene-list">
          {list.map((s, i) => (
            <SceneCard
              key={s.key}
              scene={s}
              index={i}
              count={list.length}
              project={project}
              locked={locked}
              dirty={dirty}
              collapsible
              cast={cast}
              onContinuity={flow.setSceneContinuity}
              ordered={ordered}
              onChange={draft.update}
              onMove={draft.move}
              onRemove={draft.remove}
            />
          ))}
        </ol>
        <div>
          <button type="button" className="btn" onClick={draft.add}>
            {t("Ajouter une scène")}
          </button>
        </div>
      </section>
      {dirty && blank >= 0 && (
        <p className="error" role="alert">
          Scène {blank + 1} : le texte de la voix off et le prompt visuel sont obligatoires.
        </p>
      )}
      {dirty && (
        <FormActions
          submitLabel={t("Enregistrer le plan")}
          onCancel={draft.reset}
          disabled={locked || blank >= 0 || saveBlocked !== null}
          hint={saveBlocked}
        />
      )}
    </form>
  );
}
