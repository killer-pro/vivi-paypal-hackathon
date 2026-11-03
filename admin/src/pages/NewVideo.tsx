import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage, useApi, type Project, type StyleOption } from "../api";
import type { Access } from "../access";
import AssistField from "../components/AssistField";
import Pills from "../components/Pills";
import {
  canCreate,
  DURATIONS,
  fromTemplate,
  MAX_DURATION_S,
  MIN_DURATION_S,
  parseDuration,
  styleOptions,
  titleFromSubject,
} from "../newVideo";
import { placeholderRange, TEMPLATES, type Template } from "../templates";
import "./NewVideo.css";
import TextArea from "../components/TextArea";
import { MAX_THEME } from "../limits";
import { forgetIdea, pendingIdea } from "../pendingIdea";

/** Idée, style et durée : un seul bouton crée le projet et lance la génération du plan. */
export default function NewVideo() {
  const { data: styles } = useApi<StyleOption[]>("/styles");
  const { data: access } = useApi<Access>("/access");
  // Idée saisie sur la page Découvrir avant l'inscription ; effacée une fois la vidéo créée.
  const [subject, setSubject] = useState(() => pendingIdea() ?? "");
  const [style, setStyle] = useState("");
  const [duration, setDuration] = useState("30");
  const [sceneLength, setSceneLength] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Projet déjà créé par une tentative dont le lancement a échoué : on ne le recrée pas.
  const [created, setCreated] = useState<number | null>(null);
  const navigate = useNavigate();
  const subjectField = useRef<HTMLTextAreaElement>(null);
  // Marqueur du modèle appliqué : sélectionné une fois le sujet affiché, pour que la frappe suivante le remplace.
  const selection = useRef<[number, number] | null>(null);
  useEffect(() => {
    if (!selection.current) return;
    subjectField.current?.focus();
    subjectField.current?.setSelectionRange(...selection.current);
    selection.current = null;
  }, [subject]);

  function applyTemplate(t: Template) {
    const filled = fromTemplate(t);
    setSubject(filled.subject);
    setDuration(filled.duration);
    setSceneLength(filled.sceneLength);
    selection.current = placeholderRange(t.subject);
  }

  async function createPlan() {
    setBusy(true);
    setError(null);
    let id = created;
    try {
      if (id === null) {
        const project = await api<Project>("/projects", {
          method: "POST",
          body: JSON.stringify({
            title: titleFromSubject(subject),
            theme: subject.trim(),
            target_duration_s: parseDuration(duration),
            style,
          }),
        });
        id = project.id;
        setCreated(id);
      }
      if (sceneLength !== null)
        await api(`/projects/${id}/steps/script`, {
          method: "PATCH",
          body: JSON.stringify({ params: { scene_length_s: sceneLength } }),
        });
      await api(`/projects/${id}/plan/generate`, { method: "POST" });
      forgetIdea();
      navigate(`/projects/${id}/plan`);
    } catch (err) {
      setError(
        id === null
          ? `Création impossible. ${errorMessage(err)}`
          : `Vidéo créée, mais le plan n'a pas pu démarrer. ${errorMessage(err)}`,
      );
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (canCreate(subject, duration)) void createPlan();
  }

  const invalidDuration = duration.trim() !== "" && parseDuration(duration) === null;
  return (
    <section className="composer" aria-labelledby="composer-title">
      <header className="composer-head">
        <h1 id="composer-title">Nouvelle vidéo</h1>
      </header>
      {access && !access.subscribed && (
        <p className="composer-subscribe" role="status">
          Abonnez-vous pour générer vos vidéos en entier, avec les profils et styles avancés.{" "}
          <Link to="/credits">Voir les offres</Link>
        </p>
      )}
      <form className="composer-form" onSubmit={submit}>
        <div className="templates" role="group" aria-label="Modèles de départ">
          <h2 className="templates-title">Partir d'un modèle</h2>
          <ul>
            {TEMPLATES.map((t) => (
              <li key={t.id}>
                <button type="button" className="template" disabled={busy} onClick={() => applyTemplate(t)}>
                  <strong>{t.name}</strong>
                  <span>{t.hint}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <AssistField label="Votre idée" kind="theme" value={subject} onChange={setSubject} locked={busy}>
          {(f) => (
            <TextArea
              {...f}
              ref={subjectField}
              className="input composer-subject"
              required
              maxLength={MAX_THEME}
              placeholder="Ex. 3 astuces pour mieux dormir, ton direct, public 18-30 ans"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          )}
        </AssistField>
        <div className="composer-bar">
          <Pills legend="Style" name="style" options={styleOptions(styles ?? [], access?.locked.styles, access?.reasons.style ?? "")} value={style} onChange={setStyle} disabled={busy} />
          <Pills
            legend="Durée"
            name="duration"
            options={DURATIONS.map((d) => ({ value: String(d), label: `${d} s` }))}
            value={duration}
            onChange={setDuration}
            disabled={busy}
          />
          <label className="new-duration">
            <span className="sr-only">Durée en secondes</span>
            <input
              className="input"
              type="number"
              inputMode="numeric"
              min={MIN_DURATION_S}
              max={MAX_DURATION_S}
              placeholder="Autre durée"
              aria-invalid={invalidDuration}
              disabled={busy}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </label>
          <div className="composer-actions">
            <button className="btn btn-primary btn-large" disabled={busy || !canCreate(subject, duration)}>
              {busy ? "Création du plan…" : "Créer le plan"}
            </button>
          </div>
        </div>
        {invalidDuration && (
          <p className="error" role="alert">
            La durée va de {MIN_DURATION_S} à {MAX_DURATION_S} secondes.
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
            {created !== null && (
              <>
                {" "}
                <Link to={`/projects/${created}/plan`}>Ouvrir le plan</Link>
              </>
            )}
          </p>
        )}
      </form>
    </section>
  );
}
