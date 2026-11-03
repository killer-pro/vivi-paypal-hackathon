import { useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage, useApi, type Page, type ProjectCard } from "../api";
import { DownloadIcon, PlusIcon, ProjectsIcon, SearchIcon, TrashIcon } from "../components/icons";
import Pills from "../components/Pills";
import { ConfirmDialog, ErrorState } from "../components/ui";
import { useEvents } from "../events";
import { plainTitle, usd } from "../format";
import {
  cardState,
  isFiltered,
  libraryPath,
  PAGE_SIZE,
  progress,
  SORT_LABELS,
  SORTS,
  STATUS_FILTERS,
  type Library,
  type Sort,
  type StatusFilter,
} from "../home";
import { useDebounced } from "../hooks/useDebounced";
import { STEP_LABELS, STEP_ORDER } from "../steps";
import "./Projects.css";

export default function Projects() {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [status, setStatus] = useState<StatusFilter>("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const library: Library = { search: useDebounced(search, 250), sort, status, limit };
  const { data: page, error, reload } = useApi<Page<ProjectCard>>(libraryPath(library));
  const [deleting, setDeleting] = useState<ProjectCard | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  useEvents(reload); // étape terminée ou en échec : avancement, vignette et coût changent

  const projects = page?.items;
  const filtered = isFiltered({ search, status });
  // Un changement de recherche ou de filtre repart de la première page.
  const refine = (apply: () => void) => {
    apply();
    setLimit(PAGE_SIZE);
  };

  async function remove(project: ProjectCard) {
    setDeleting(null);
    try {
      await api(`/projects/${project.id}`, { method: "DELETE" });
      setDeleteError(null);
    } catch (err) {
      setDeleteError(`Suppression de « ${project.title} » impossible. ${errorMessage(err)}`);
    }
    reload();
  }

  return (
    <div className="home">
      <section className="library" aria-labelledby="library-title">
        <header className="library-head">
          <h1 id="library-title">Vos vidéos</h1>
          {page && <span className="count">{page.total}</span>}
          <Link className="btn btn-primary library-new" to="/new">
            <PlusIcon /> Nouvelle vidéo
          </Link>
        </header>
        {(page === undefined || page.total > 0 || filtered) && (
          <div className="library-tools">
            <label className="search input-search">
              <span className="sr-only">Rechercher une vidéo</span>
              <SearchIcon />
              <input
                className="input"
                type="search"
                placeholder="Rechercher par titre ou sujet"
                value={search}
                onChange={(e) => refine(() => setSearch(e.target.value))}
              />
            </label>
            <Pills
              legend="Afficher"
              name="status"
              hideLegend
              options={STATUS_FILTERS}
              value={status}
              onChange={(v) => refine(() => setStatus(v))}
            />
            <label className="sort">
              <span className="sr-only">Trier par</span>
              <select className="input" aria-label="Trier par" value={sort} onChange={(e) => refine(() => setSort(e.target.value as Sort))}>
                {SORTS.map((s) => (
                  <option key={s} value={s}>
                    {SORT_LABELS[s]}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {deleteError && (
          <p className="error page-error" role="alert">
            {deleteError}
          </p>
        )}
        {error && <ErrorState message={error} onRetry={reload} />}
        {!error && !projects && (
          <ul className="cards" aria-busy="true" aria-label="Chargement des vidéos">
            {Array.from({ length: 5 }, (_, i) => (
              <li key={i} className="card-skeleton" />
            ))}
          </ul>
        )}
        {!error && projects?.length === 0 && !filtered && (
          <div className="library-empty library-welcome">
            <ProjectsIcon />
            <h2>Aucune vidéo pour l'instant</h2>
            <p className="muted">Décrivez une idée : le script, les clips, la voix et le montage se génèrent étape par étape.</p>
            <Link className="btn btn-primary" to="/new">
              <PlusIcon /> Nouvelle vidéo
            </Link>
          </div>
        )}
        {!error && projects?.length === 0 && filtered && (
          <div className="library-empty">
            <p>Aucune vidéo ne correspond à cette recherche.</p>
            <button
              className="btn"
              onClick={() =>
                refine(() => {
                  setSearch("");
                  setStatus("");
                })
              }
            >
              Effacer la recherche et les filtres
            </button>
          </div>
        )}
        {!error && projects && projects.length > 0 && (
          <ul className="cards">
            {projects.map((p) => (
              <ProjectTile key={p.id} project={p} onDelete={() => setDeleting(p)} />
            ))}
          </ul>
        )}
        {!error && page && projects && projects.length < page.total && (
          <div className="library-more">
            <button className="btn" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
              Afficher plus ({page.total - projects.length} restante{page.total - projects.length > 1 ? "s" : ""})
            </button>
          </div>
        )}
      </section>

      {deleting && (
        <ConfirmDialog
          title="Supprimer la vidéo ?"
          message={`« ${deleting.title} » sera supprimée avec ses clips, voix et rendus. Cette action est définitive.`}
          confirmLabel="Supprimer"
          onConfirm={() => remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}

/** Carte 9:16 : vignette (ou aplat à la couleur de l'état), titre, avancement sur 8 étapes, état et coût. */
function ProjectTile({ project: p, onDelete }: { project: ProjectCard; onDelete: () => void }) {
  const state = cardState(p);
  const segments = progress(p.current_step);
  const position = p.current_step
    ? `Étape ${STEP_ORDER.indexOf(p.current_step) + 1} sur 8 : ${STEP_LABELS[p.current_step]}`
    : "8 étapes sur 8";
  return (
    <li className={`card st-${state.tone}${state.live ? " is-live" : ""}`}>
      <div className="card-frame">
        {p.thumbnail_url ? (
          <video className="card-thumb" src={`${p.thumbnail_url}#t=0.5`} muted playsInline preload="metadata" />
        ) : (
          <span className="card-empty">
            <ProjectsIcon />
            Pas encore de clip
          </span>
        )}
      </div>
      <Link className="card-title" to={`/projects/${p.id}`}>
        {plainTitle(p.title)}
      </Link>
      <div className="progress" role="img" aria-label={position}>
        {segments.map((s, i) => (
          <span key={i} className={`seg seg-${s}`} />
        ))}
      </div>
      <p className="card-meta">
        <span className="card-state">{state.label}</span>
        {p.cost_usd > 0 && (
          <span className="muted" title="Dépensé sur cette vidéo">
            {usd.format(p.cost_usd)}
          </span>
        )}
      </p>
      {p.render_asset_id !== null && (
        <a className="card-export" href={`/api/projects/${p.id}/assets/${p.render_asset_id}/download`}>
          <DownloadIcon /> Exporter
        </a>
      )}
      <button className="card-delete" onClick={onDelete} aria-label={`Supprimer « ${p.title} »`} title="Supprimer">
        <TrashIcon />
      </button>
    </li>
  );
}
