import { useState } from "react";
import { Link } from "react-router-dom";
import { runningDownstream } from "../../steps";
import { QUEUE_HINT, QUEUE_LABEL } from "../../studio";
import { referenceBlocked, type Access } from "../../access";
import { referenceElements, referenceImage, useApi, storyElementsWithoutReference, type ProviderModels, type ReferenceElement, type Step } from "../../api";
import type { CastMember } from "../../casting";
import { choiceKey, choiceOf, imageBlocked, imageChoice, imageOptions, type Choice } from "../../models";
import type { PanelProps } from "../StepPanel";
import { useConfirm } from "../../hooks/useConfirm";
import { Field } from "../ui";
import PromptEditor from "./PromptEditor";
import TextArea from "../TextArea";

interface Props extends Pick<PanelProps, "flow" | "project" | "locked" | "runLocked"> {
  refStep: Step;
  /** Casting du projet (`castOf`), dont le bandeau `CastStrip` montre déjà les images. */
  cast: CastMember[];
  models: { data?: ProviderModels; error: string | null };
  /** Générateur d'image par défaut (réglage `image_provider`). */
  imageDefault: string;
}

/** Édition d'un élément récurrent du script (personnage, produit) : son prompt, régénération et import ; son image est
 *  dans le bandeau du casting. */
function ElementCard({ member, prompt, onPrompt, noGenerate, noUpload, queueing, onGenerate, onUpload }: {
  member: CastMember;
  prompt: string;
  onPrompt: (value: string) => void;
  /** Génération impossible (file pleine, action en cours, générateur indisponible). */
  noGenerate: boolean;
  /** Import impossible : l'API refuse de changer les images pendant que l'étape ou les clips tournent. */
  noUpload: boolean;
  /** La génération partira en file d'attente. */
  queueing: boolean;
  onGenerate: () => void;
  onUpload: (file: File) => void;
}) {
  const { name, scenes } = member;
  return (
    <div className="reference-card">
      <strong>{name}</strong>
      <span className="muted">{scenes.length ? `Scène${scenes.length > 1 ? "s" : ""} ${scenes.join(", ")}` : "Aucune scène"}</span>
      <TextArea className="input" rows={4} aria-label={`Prompt de l'image « ${name} »`} value={prompt} onChange={(e) => onPrompt(e.target.value)} />
      <div className="form-actions">
        <label className="btn btn-small" title="Utiliser une image locale pour cet élément">
          Importer
          <input type="file" accept="image/*" hidden disabled={noUpload} onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
        </label>
        <button className="btn btn-small" onClick={onGenerate} disabled={noGenerate} title={queueing ? QUEUE_HINT : undefined}>
          {queueing ? QUEUE_LABEL : member.imageUrl ? "Régénérer" : "Générer"}
        </button>
      </div>
    </div>
  );
}

/** Éléments au plus (miroir de `MAX_REFERENCES_TOTAL` côté API). */
const MAX_REFERENCE_ELEMENTS = 12;

/** Formulaire d'ajout d'un élément que le script n'a pas listé (autre personnage, objet) : nom + description de l'image. */
function AddElement({ onAdd }: { onAdd: (name: string, prompt: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  if (!open) {
    return (
      <div>
        <button className="btn btn-small" onClick={() => setOpen(true)}>
          Ajouter un élément
        </button>
      </div>
    );
  }
  const submit = async () => {
    if (!(await onAdd(name.trim(), prompt.trim()))) return;
    setName("");
    setPrompt("");
    setOpen(false);
  };
  return (
    <div className="add-element">
      <Field label="Nom de l'élément">
        <input className="input" placeholder="Ex. : Ouvrier de l'Égypte ancienne" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Description de l'image">
        <TextArea className="input" rows={3} placeholder="Ex. : Un ouvrier égyptien au torse nu, pagne de lin, peau hâlée, portant un bloc de pierre" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </Field>
      <div className="form-actions">
        <button className="btn btn-ghost btn-small" onClick={() => setOpen(false)}>
          Annuler
        </button>
        <button className="btn btn-small" onClick={submit} disabled={!name.trim() || !prompt.trim()}>
          Ajouter
        </button>
      </div>
    </div>
  );
}

/** Édition des images de référence (prompts, import, régénération, ajout d'un élément) : une par élément récurrent du
 *  script (personnage, produit, marque), que chaque scène reprend ; sans élément, une image de style commune à tous les
 *  clips. */
export default function ReferenceSection({ flow, project, locked, runLocked, refStep, cast, models, imageDefault }: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  const [pick, setPick] = useState<Choice | null>(null);
  const { confirm, dialog } = useConfirm();
  /** Lance la génération ; si l'image existe déjà, demande d'abord confirmation (elle serait remplacée). */
  const generate = (replaces: boolean, what: string, run: () => void) =>
    replaces
      ? confirm({
          title: `Régénérer ${what} ?`,
          message: "L'image actuelle sera remplacée ; la génération est facturée selon le générateur choisi.",
          confirmLabel: "Régénérer",
          onConfirm: run,
        })
      : run();
  // Prompts, choix du générateur et demandes de génération restent libres pendant une génération (la demande part en
  // file) ; l'import d'image n'est refusé par l'API que pendant l'étape reference elle-même (les clips en cours ont déjà lu
  // leurs images : la nouvelle sert aux suivants).
  const queueing = refStep.status === "running" || runningDownstream(project.steps, "reference").length > 0;
  const elements = referenceElements(project.steps);
  const fromStory = storyElementsWithoutReference(project.steps);
  const image = referenceImage(project.assets, "");
  const members = new Map(cast.map((m) => [m.id, m]));
  const made = elements.filter((e) => members.get(e.id)?.imageUrl).length;
  // Prompts modifiés par élément : brouillon local, sinon ceux de l'étape, sinon celui du script.
  const [edited, setEdited] = useState<Record<string, string>>({});
  const savedPrompts = (refStep.params.prompts ?? {}) as Record<string, string>;
  const promptOf = (e: ReferenceElement) => edited[e.id] ?? savedPrompts[e.id] ?? e.prompt;
  const allPrompts = Object.fromEntries(elements.map((e) => [e.id, promptOf(e)]));
  const saved = String(refStep.params.prompt ?? "");
  const prompt = draft ?? saved;
  // Choix d'image : brouillon local, sinon celui de l'étape (Gemini par défaut s'il est disponible).
  const choice =
    pick ??
    imageChoice(
      models.data?.image,
      { provider: refStep.params.provider as string | undefined, model: refStep.params.model as string | undefined },
      imageDefault,
    );
  const blocked = imageBlocked(models.data?.image, models.error, choice);
  // Image de référence réservée à l'abonnement : les contrôles restent visibles, désactivés, avec le motif.
  const subscriptionLock = referenceBlocked(useApi<Access>("/access").data);

  return (
    // Repliée : les images elles-mêmes sont dans le bandeau du casting, ce volet ne sert qu'à les modifier.
    <details className="advanced">
      <summary>
        Image de référence
        {elements.length > 0 && <span className="advanced-badge">{made}/{elements.length} générées</span>}
        {elements.length === 0 && image && <span className="advanced-badge">générée</span>}
        {!image && made === 0 && refStep.status === "pending" && <span className="advanced-badge muted"> facultative</span>}
      </summary>
      <div className="advanced-body">
        {elements.length > 0 ? (
          <>
            <div className="reference-grid">
              {elements.map((e) => {
                const member = members.get(e.id);
                return (
                  member && (
                    <ElementCard
                      key={e.id}
                      member={member}
                      prompt={promptOf(e)}
                      onPrompt={(value) => setEdited((p) => ({ ...p, [e.id]: value }))}
                      noGenerate={runLocked || Boolean(blocked) || Boolean(subscriptionLock)}
                      noUpload={flow.busy || refStep.status === "running" || Boolean(subscriptionLock)}
                      queueing={queueing}
                      onGenerate={() =>
                        generate(Boolean(member.imageUrl), `l'image « ${member.name} »`, () =>
                          flow.run("reference", undefined, { params: { prompts: allPrompts, ...choice }, overrides: { reference_id: e.id } }),
                        )
                      }
                      onUpload={(file) => flow.uploadReference(file, e.id)}
                    />
                  )
                );
              })}
            </div>
          </>
        ) : (
          <>
            {image && <img className="frame-9x16 reference-image" src={image.url} alt="Image de référence générée" />}
            <PromptEditor
              title="Prompt de l'image"
              fieldLabel="Description du style visuel"
              placeholder="Par défaut : le thème du projet, format vertical, style cinématographique"
              instructionPlaceholder='Ex. : "Style film noir années 50", "Tons chauds, lumière naturelle"...'
              rows={3}
              value={prompt}
              original={saved}
              onChange={setDraft}
              assist={{ kind: "reference_prompt", context: { projectId: project.id } }}
            />
          </>
        )}

        {elements.length < MAX_REFERENCE_ELEMENTS && fromStory.length > 0 && (
          <div className="story-elements">
            <span className="muted">Éléments de l'histoire sans image de référence</span>
            <div className="story-elements-list">
              {fromStory.map((e) => (
                <button key={e.id} className="btn btn-small" disabled={flow.busy} title={e.prompt} onClick={() => flow.addReference(e.name, e.prompt, e.id)}>
                  + {e.name}
                </button>
              ))}
            </div>
          </div>
        )}
        {elements.length < MAX_REFERENCE_ELEMENTS && <AddElement onAdd={flow.addReference} />}

        <Field label="Générateur d'image">
          <select className="input" value={choiceKey(choice)} onChange={(e) => setPick(choiceOf(e.target.value))}>
            {imageOptions(models.data?.image, choice).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>

        {subscriptionLock && <p className="muted">{subscriptionLock}</p>}
        {blocked && (
          <p className="muted">
            {blocked} <Link to="/providers">Ouvrir les Réglages</Link>
          </p>
        )}
        <div className="form-actions">
          {refStep.status === "pending" && (
            <button className="btn btn-ghost" onClick={() => flow.approve("reference")} disabled={locked || queueing}>
              Ignorer cette étape
            </button>
          )}
          <button
            className="btn btn-primary"
            onClick={() =>
              generate(elements.length ? made > 0 : Boolean(image), elements.length ? "toutes les images" : "l'image", () =>
                flow.run("reference", undefined, { params: { ...(elements.length ? { prompts: allPrompts } : { prompt }), ...choice } }),
              )
            }
            disabled={runLocked || Boolean(blocked) || Boolean(subscriptionLock)}
            title={queueing ? QUEUE_HINT : undefined}
          >
            {queueing ? QUEUE_LABEL : elements.length ? (made ? "Régénérer toutes les images" : "Générer toutes les images") : image ? "Régénérer l'image" : "Générer l'image"}
          </button>
        </div>
      </div>
      {dialog}
    </details>
  );
}
