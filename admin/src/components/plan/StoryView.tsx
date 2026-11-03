import { useState, type FormEvent, type ReactNode } from "react";
import type { useStoryDraft } from "../../hooks/useStoryDraft";
import { voiceLabel, withCurrent, type Voice } from "../../settings";
import { CONTINUITY_LABELS, ELEMENT_KINDS, elementCounts, speakingElements, type Continuity, type DraftBeat, type ElementKind, type StoryElement } from "../../story";
import TextArea from "../TextArea";
import "../Cast.css";
import { Field, FormActions } from "../ui";

type Draft = ReturnType<typeof useStoryDraft>;

interface Props {
  draft: Draft;
  warnings: string[];
  locked: boolean;
  /** Catalogue de voix des réglages, pour la voix de chaque personnage. */
  voices: Voice[];
  /** Durée visée pour la vidéo, rappelée à côté de la somme des beats. */
  targetS: number;
  onSave: (e: FormEvent) => void;
}

/** Histoire éditable : fiche de style, éléments suivis (personnages, accessoires, lieux) puis beats et ce qu'on y voit. */
export default function StoryView({ draft, warnings, locked, voices, targetS, onSave }: Props) {
  const { story, dirty, total, unknown, blank } = draft;
  return (
    <form className="form plan-view" onSubmit={onSave}>
      {warnings.length > 0 && (
        <ul className="story-warnings" role="status">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <section className="plan-section" aria-labelledby="story-style">
        <h2 id="story-style">Style</h2>
        <Field label="Style, décor et palette (en anglais)">
          <TextArea className="input" rows={3} value={story.bible} onChange={(e) => draft.setBible(e.target.value)} />
        </Field>
      </section>

      <section className="plan-section" aria-labelledby="story-elements">
        <SectionHead id="story-elements" title="Éléments suivis" count={elementCounts(story.elements)} />
        <p className="muted story-lead">Leur apparence est recopiée à l'identique dans chaque scène où ils apparaissent.</p>
        {story.elements.length > 0 ? (
          <ul className="scene-list">
            {story.elements.map((e) => (
              <ElementCard key={e.id} element={e} locked={locked} voices={voices} draft={draft} />
            ))}
          </ul>
        ) : (
          <EmptyNote>
            Aucun élément suivi : ajoutez le personnage, l'accessoire ou le lieu qui doit rester identique d'une scène à
            l'autre.
          </EmptyNote>
        )}
        <AddElement locked={locked} onAdd={draft.addElement} />
      </section>

      <section className="plan-section" aria-labelledby="story-beats">
        <SectionHead
          id="story-beats"
          title="Beats"
          count={`${story.beats.length} beat${story.beats.length > 1 ? "s" : ""}, ${total.toLocaleString("fr-FR")} s sur ${targetS} s visées`}
        />
        <p className="muted story-lead">Chaque beat deviendra une scène.</p>
        {story.beats.length > 0 ? (
          <ol className="scene-list">
            {story.beats.map((b, i) => (
              <BeatCard key={b.key} beat={b} index={i} count={story.beats.length} elements={story.elements} draft={draft} />
            ))}
          </ol>
        ) : (
          <EmptyNote>Aucun beat : ajoutez-en un pour chaque moment de la vidéo.</EmptyNote>
        )}
        <div>
          <button type="button" className="btn" onClick={draft.addBeat}>
            Ajouter un beat
          </button>
        </div>
      </section>

      {dirty && unknown.length > 0 && (
        <p className="error" role="alert">
          Élément inconnu dans un beat : {unknown.join(", ")}.
        </p>
      )}
      {dirty && blank >= 0 && (
        <p className="error" role="alert">
          Beat {blank + 1} : le résumé et la voix off sont obligatoires.
        </p>
      )}
      {dirty && (
        <FormActions
          submitLabel="Enregistrer l'histoire"
          onCancel={draft.reset}
          disabled={locked || unknown.length > 0 || blank >= 0}
        />
      )}
    </form>
  );
}

/** Titre de section et son compteur (absent s'il est vide), comme la section Scènes du plan. */
function SectionHead({ id, title, count }: { id: string; title: string; count: string }) {
  return (
    <div className="plan-section-head">
      <h2 id={id}>{title}</h2>
      {count && <span className="muted">{count}</span>}
    </div>
  );
}

/** Section sans contenu : ce qui manque et quoi ajouter. */
function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="empty story-empty">{children}</p>;
}

function ElementCard({
  element: e,
  locked,
  voices,
  draft,
}: {
  element: StoryElement;
  locked: boolean;
  voices: Voice[];
  draft: Draft;
}) {
  return (
    <li className="scene-card">
      <div className="scene-card-head">
        <h4>{e.name || e.id}</h4>
        <span className="cast-chip">{ELEMENT_KINDS[e.kind]}</span>
        <div className="scene-card-tools">
          <button type="button" className="btn btn-ghost btn-small" disabled={locked} onClick={() => draft.removeElement(e.id)}>
            Supprimer
          </button>
        </div>
      </div>
      <div className="scene-fields">
        <div className="story-row">
          <Field label="Nom">
            <input className="input" value={e.name} onChange={(ev) => draft.updateElement(e.id, { name: ev.target.value })} />
          </Field>
          <Field label="Type">
            <select
              className="input"
              value={e.kind}
              onChange={(ev) => draft.updateElement(e.id, { kind: ev.target.value as ElementKind })}
            >
              {Object.entries(ELEMENT_KINDS).map(([kind, label]) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Apparence figée (en anglais)">
          <TextArea className="input" value={e.descriptor} onChange={(ev) => draft.updateElement(e.id, { descriptor: ev.target.value })} />
        </Field>
        {e.kind === "character" && (
          <Field label="Voix quand il parle">
            <select className="input" value={e.voice_id} onChange={(ev) => draft.updateElement(e.id, { voice_id: ev.target.value })}>
              <option value="">Voix par défaut</option>
              {withCurrent(voices.map((v) => v.id), e.voice_id).map((id) => (
                <option key={id} value={id}>
                  {voiceLabel(voices, id)}
                </option>
              ))}
            </select>
          </Field>
        )}
        {e.kind !== "place" && (
          <Field label="Image de référence (prompt, en anglais)">
            <TextArea className="input" value={e.prompt} onChange={(ev) => draft.updateElement(e.id, { prompt: ev.target.value })} />
          </Field>
        )}
      </div>
    </li>
  );
}

function AddElement({ locked, onAdd }: { locked: boolean; onAdd: (name: string) => void }) {
  const [name, setName] = useState("");
  const add = () => {
    if (!name.trim()) return;
    onAdd(name.trim());
    setName("");
  };
  return (
    <div className="story-add">
      <input
        className="input"
        placeholder="Nom du nouvel élément"
        aria-label="Nom du nouvel élément"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault(); // pas d'envoi du formulaire de l'histoire
            add();
          }
        }}
      />
      <button type="button" className="btn" disabled={locked || !name.trim()} onClick={add}>
        Ajouter un élément
      </button>
    </div>
  );
}

function BeatCard({
  beat: b,
  index: i,
  count,
  elements,
  draft,
}: {
  beat: DraftBeat;
  index: number;
  count: number;
  elements: StoryElement[];
  draft: Draft;
}) {
  const present = new Map(b.elements.map((e) => [e.id, e.state]));
  return (
    <li className="scene-card">
      <div className="scene-card-head">
        <h4>Beat {i + 1}</h4>
        {Number.isFinite(b.duration_s) && <span className="muted">{b.duration_s.toLocaleString("fr-FR")} s</span>}
        <div className="scene-card-tools">
          <button type="button" className="btn btn-ghost btn-small" disabled={i === 0} onClick={() => draft.moveBeat(i, -1)}>
            Monter
          </button>
          <button type="button" className="btn btn-ghost btn-small" disabled={i === count - 1} onClick={() => draft.moveBeat(i, 1)}>
            Descendre
          </button>
          <button type="button" className="btn btn-ghost btn-small" onClick={() => draft.removeBeat(i)}>
            Supprimer
          </button>
        </div>
      </div>
      <div className="scene-fields">
        <Field label="Ce qui se passe">
          <TextArea className="input" required value={b.summary} onChange={(e) => draft.updateBeat(b.key, { summary: e.target.value })} />
        </Field>
        <Field label="Texte de la voix off">
          <TextArea className="input" required value={b.voice_text} onChange={(e) => draft.updateBeat(b.key, { voice_text: e.target.value })} />
        </Field>
        <div className="story-row">
          <Field label="Durée (s)">
            <input
              className="input input-narrow"
              type="number"
              required
              min={0.5}
              step={0.5}
              value={b.duration_s}
              onChange={(e) => draft.updateBeat(b.key, { duration_s: e.target.valueAsNumber })}
            />
          </Field>
          <Field label="Qui parle">
            <select className="input" value={b.speaker} onChange={(e) => draft.updateBeat(b.key, { speaker: e.target.value })}>
              <option value="">Le narrateur</option>
              {speakingElements(elements).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name || c.id}
                </option>
              ))}
            </select>
          </Field>
          {i > 0 && (
            <Field label="Enchaînement">
              <select
                className="input"
                value={b.continuity}
                onChange={(e) => draft.updateBeat(b.key, { continuity: e.target.value as Continuity })}
              >
                {Object.entries(CONTINUITY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
        <fieldset className="story-presence">
          <legend>Visible dans ce beat</legend>
          {elements.map((e) => (
            <div key={e.id} className="story-presence-row">
              <label>
                <input
                  type="checkbox"
                  checked={present.has(e.id)}
                  onChange={(ev) => draft.setPresence(b.key, e.id, ev.target.checked ? "" : null)}
                />
                {e.name || e.id}
              </label>
              {present.has(e.id) && (
                <input
                  className="input"
                  aria-label={`État de ${e.name || e.id}`}
                  placeholder="État (en anglais), ex. wet"
                  value={present.get(e.id)}
                  onChange={(ev) => draft.setPresence(b.key, e.id, ev.target.value)}
                />
              )}
            </div>
          ))}
        </fieldset>
      </div>
    </li>
  );
}
