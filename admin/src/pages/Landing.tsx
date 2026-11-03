import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../api";
import type { Me } from "../auth";
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, ChevronUpIcon, SparkleIcon } from "../components/icons";
import ClipWall, { Clip } from "../components/ClipWall";
import { clip, FORMATS, IDEA_EXAMPLES, moveScene, nextScene, PIPELINE, SCENE_IDS, SCENES, STRENGTHS, STYLES, USE_CASES, wide, type SceneId } from "../landing";
import { MAX_THEME } from "../limits";
import { reducedMotion } from "../motion";
import { cleanIdea, rememberIdea } from "../pendingIdea";
import "./Landing.css";

/** Grille de clips verticaux légendés, décalés une colonne sur deux. */
function Usages({ items }: { items: { name: string; art: string; line: string }[] }) {
  return (
    <ul className="lp-usages">
      {items.map((u) => (
        <li key={u.name} className="lp-usage">
          <Clip name={u.art} />
          <div className="lp-usage-text">
            <h3>{u.name}</h3>
            <p>{u.line}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Téléphone 9:16 qui enchaîne les clips dans l'ordre choisi : le seul moment interactif de la page. */
function ScenePlayer() {
  const [order, setOrder] = useState(SCENE_IDS);
  const [current, setCurrent] = useState<SceneId>(SCENE_IDS[0]);
  const autoPlay = !reducedMotion();

  return (
    <div className="lp-player">
      <div className="lp-phone">
        <video
          key={current}
          className="lp-phone-video"
          src={clip(current, "mp4")}
          poster={clip(current, "jpg")}
          autoPlay={autoPlay}
          muted
          playsInline
          controls={!autoPlay}
          onEnded={() => setCurrent(nextScene(order, current))}
        />
      </div>
      <div className="lp-sequence">
        <h3 className="lp-sequence-title">Ordre de lecture</h3>
        <ol className="lp-sequence-list">
          {order.map((id, i) => (
            <li key={id} className={`lp-sequence-item${id === current ? " is-current" : ""}`}>
              <button type="button" className="lp-sequence-pick" onClick={() => setCurrent(id)} aria-current={id === current}>
                <img className="lp-sequence-thumb" src={clip(id, "jpg")} alt="" width={36} height={64} />
                <span>
                  <span className="lp-sequence-name">
                    {i + 1}. {SCENES[id].title}
                  </span>
                  <span className="lp-sequence-line">{SCENES[id].line}</span>
                </span>
              </button>
              <span className="lp-sequence-moves">
                <button type="button" className="btn btn-icon btn-small btn-ghost" aria-label={`Monter ${SCENES[id].title}`}
                  disabled={i === 0} onClick={() => setOrder(moveScene(order, id, -1))}>
                  <ChevronUpIcon />
                </button>
                <button type="button" className="btn btn-icon btn-small btn-ghost" aria-label={`Descendre ${SCENES[id].title}`}
                  disabled={i === order.length - 1} onClick={() => setOrder(moveScene(order, id, 1))}>
                  <ChevronDownIcon />
                </button>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

/** Carrousel horizontal des étapes ; défilement par le doigt, la molette ou les deux flèches. */
function PipelineCarousel() {
  const track = useRef<HTMLOListElement>(null);

  function scroll(direction: -1 | 1) {
    const el = track.current;
    if (!el?.firstElementChild) return;
    const step = el.firstElementChild.clientWidth + 16; // largeur d'une carte + l'espace entre deux
    el.scrollBy({ left: direction * step, behavior: reducedMotion() ? "auto" : "smooth" });
  }

  return (
    <>
      <div className="lp-head">
        <h2>De l'idée à l'export, sans changer d'outil</h2>
        <span className="lp-arrows">
          <button type="button" className="btn btn-icon btn-large" aria-label="Étape précédente" onClick={() => scroll(-1)}>
            <ChevronLeftIcon />
          </button>
          <button type="button" className="btn btn-icon btn-large" aria-label="Étape suivante" onClick={() => scroll(1)}>
            <ChevronRightIcon />
          </button>
        </span>
      </div>
      <ol className="lp-track" ref={track} tabIndex={0} aria-label="Étapes du pipeline">
        {PIPELINE.map((step, i) => (
          <li key={step.name} className="lp-card">
            <img src={wide(step.art)} alt="" loading="lazy" />
            <div className="lp-card-text">
              <span className="lp-card-n">{i + 1} / {PIPELINE.length}</span>
              <h3>{step.name}</h3>
              <p>{step.does}</p>
            </div>
          </li>
        ))}
      </ol>
    </>
  );
}

/** Barre de recherche IA : l'idée est gardée, puis le visiteur est envoyé créer sa vidéo (connecté) ou son compte. */
function IdeaBar({ connected }: { connected: boolean }) {
  const [idea, setIdea] = useState("");
  const navigate = useNavigate();

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!cleanIdea(idea)) return;
    rememberIdea(idea);
    navigate(connected ? "/new" : "/register");
  }

  return (
    <form className="lp-idea" onSubmit={submit}>
      <div className="lp-idea-bar">
        <SparkleIcon />
        <input
          type="text"
          aria-label="Décrivez la vidéo que vous voulez créer"
          placeholder="Décrivez votre vidéo…"
          maxLength={MAX_THEME}
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
        />
        <button className="btn btn-primary btn-large" disabled={!cleanIdea(idea)}>
          Créer ma vidéo
        </button>
      </div>
      <ul className="lp-idea-examples" aria-label="Idées pour commencer">
        {IDEA_EXAMPLES.map((example) => (
          <li key={example}>
            <button type="button" className="lp-idea-chip" onClick={() => setIdea(example)}>
              {example}
            </button>
          </li>
        ))}
      </ul>
    </form>
  );
}

export default function Landing() {
  const connected = useApi<Me>("/auth/me").data !== undefined;
  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="landing-brand">
          <span className="brand-mark" aria-hidden />
          Vivi
        </span>
        <nav className="landing-nav">
          {connected ? (
            <Link className="btn btn-primary" to="/">Ouvrir l'application</Link>
          ) : (
            <>
              <Link className="btn btn-ghost" to="/login">Se connecter</Link>
              <Link className="btn btn-primary" to="/register">S'inscrire</Link>
            </>
          )}
        </nav>
      </header>

      <main>
        <section className="lp-hero">
          <ClipWall />
          <div className="lp-hero-copy">
            <h1>Une idée en entrée. Une vidéo verticale en sortie.</h1>
            <p className="lp-hero-lead">
              Produit, appartement, collection, histoire à suspense, clip anime : pour TikTok, YouTube Shorts et Reels,
              décrivez-le, l'outil écrit, filme, met en voix et monte.
            </p>
            <IdeaBar connected={connected} />
          </div>
        </section>

        <section className="lp-section" id="usages">
          <h2 className="lp-title">Tout ce que vous vendez peut avoir sa vidéo</h2>
          <Usages items={USE_CASES} />
        </section>

        <section className="lp-section" id="styles">
          <h2 className="lp-title">Pour TikTok, YouTube Shorts et Reels, dans le style qui vous ressemble</h2>
          <Usages items={STYLES} />
          <Usages items={FORMATS} />
        </section>

        <section className="lp-section lp-split" id="scenes">
          <h2 className="lp-title">Les scènes sont indépendantes : changez l'ordre, la pub se remonte</h2>
          <ScenePlayer />
        </section>

        <section className="lp-section lp-section-flush" id="pipeline">
          <PipelineCarousel />
        </section>

        <section className="lp-section">
          <h2 className="lp-title">Pensé pour tourner chez vous</h2>
          <dl className="lp-strengths">
            {STRENGTHS.map((s) => (
              <div key={s.title} className="lp-strength">
                <dt>{s.title}</dt>
                <dd>{s.text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="lp-closing">
          <img className="lp-closing-media" src={wide("conclusion")} alt="" loading="lazy" />
          <div className="lp-closing-copy">
            <h2>Essayez avec votre première idée</h2>
            <IdeaBar connected={connected} />
          </div>
        </section>
      </main>
    </div>
  );
}
