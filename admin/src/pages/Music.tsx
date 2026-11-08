import { useState } from "react";
import { api, errorMessage, useApi, type MusicTrack } from "../api";
import AudioPlayer from "../components/AudioPlayer";
import ImportTrack from "../components/ImportTrack";
import { TrashIcon } from "../components/icons";
import { ConfirmDialog, ErrorState } from "../components/ui";
import { clock } from "../format";
import "./Music.css";
import { t } from "../i18n";

export default function Music() {
  const { data: tracks, error, reload } = useApi<MusicTrack[]>("/music");
  const [deleting, setDeleting] = useState<MusicTrack | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function remove(track: MusicTrack) {
    setDeleting(null);
    setDeleteError(null);
    try {
      await api(`/music/${track.id}`, { method: "DELETE" });
    } catch (err) {
      setDeleteError(t("Suppression de « {title} » impossible. {error}", { title: track.name, error: errorMessage(err) }));
    }
    reload();
  }

  const importButton = <ImportTrack primary onImported={reload} />;

  return (
    <>
      <header className="page-head">
        <h1>{t("Musique")}</h1>
        {tracks && tracks.length > 0 && (
          <>
            <span className="muted">{tracks.length}</span>
            <div className="page-head-actions">{importButton}</div>
          </>
        )}
      </header>

      {error && <ErrorState message={error} onRetry={reload} />}
      {!error && !tracks && <p className="muted">{t("Chargement…")}</p>}
      {deleteError && (
        <p className="error page-error" role="alert">
          {deleteError}
        </p>
      )}

      {!error && tracks?.length === 0 && (
        <section className="empty">
          <h2>{t("Aucune piste dans la bibliothèque")}</h2>
          <p className="muted">
            {t("Importez des musiques de fond (MP3, WAV…, 50 Mo maximum) : elles seront proposées à l'étape Musique de chaque vidéo.")}
          </p>
          {importButton}
        </section>
      )}

      {!error && tracks && tracks.length > 0 && (
        <div className="table-wrap">
          <table className="table music-table">
            <thead>
              <tr>
                <th>{t("Nom")}</th>
                <th>{t("Tags")}</th>
                <th className="num">{t("Durée")}</th>
                <th>{t("Écoute")}</th>
                <th>
                  <span className="sr-only">{t("Actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {tracks.map((track) => (
                <tr key={track.id}>
                  <td className="track-title">{track.name}</td>
                  <td>
                    {track.tags.length > 0 ? (
                      <ul className="tags">
                        {track.tags.map((tag) => (
                          <li key={tag}>{tag}</li>
                        ))}
                      </ul>
                    ) : (
                      <span className="muted">{t("Aucun")}</span>
                    )}
                  </td>
                  <td className="num">{clock(track.duration_s)}</td>
                  <td>
                    <AudioPlayer src={track.url} label={track.name} />
                  </td>
                  <td className="num">
                    <button
                      className="btn btn-ghost btn-danger btn-icon"
                      onClick={() => setDeleting(track)}
                      title={t("Supprimer la piste")}
                      aria-label={t("Supprimer « {name} »", { name: track.name })}
                    >
                      <TrashIcon />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleting && (
        <ConfirmDialog
          title={t("Supprimer la piste")}
          message={t("« {name} » sera retirée de la bibliothèque. Une vidéo qui l'a choisie devra changer de musique avant son prochain montage.", { name: deleting.name })}
          confirmLabel={t("Supprimer")}
          onConfirm={() => remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </>
  );
}
