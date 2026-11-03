import AudioPlayer from "../AudioPlayer";
import type { ReactNode } from "react";
import { useApi, type MusicTrack } from "../../api";
import StepPanel, { type PanelProps } from "../StepPanel";
import ImportTrack from "../ImportTrack";
import { ErrorState } from "../ui";
import { clock } from "../../format";
import { useMe } from "../../hooks/useMe";

export default function MusicPanel(props: PanelProps) {
  const { flow, step, locked } = props;
  const tracks = useApi<MusicTrack[]>("/music");
  const isAdmin = useMe()?.role === "admin"; // la bibliothèque est commune : seul l'administrateur l'enrichit
  const selected = (step.params.track_id as number | null | undefined) ?? null;
  const choose = (trackId: number | null) => flow.patch("music", { params: { ...step.params, track_id: trackId } });

  const option = (id: number | null, children: ReactNode) => (
    <label key={id ?? "none"} className={selected === id ? "track is-chosen" : "track"}>
      <input type="radio" name="track" checked={selected === id} disabled={locked} onChange={() => choose(id)} />
      {children}
    </label>
  );

  return (
    <StepPanel {...props} runLabel="Confirmer le choix">
      {isAdmin && (
        <div className="track-import">
          <ImportTrack
            onImported={(track) => {
              tracks.reload();
              if (!locked) choose(track.id); // la piste importée est aussitôt choisie
            }}
          />
        </div>
      )}
      {tracks.error && <ErrorState message={tracks.error} onRetry={tracks.reload} />}
      {!tracks.data && !tracks.error && <p className="muted">Chargement de la bibliothèque…</p>}
      {tracks.data && (
        <div className="track-list" role="radiogroup" aria-label="Musique de fond">
          {tracks.data.map((t) =>
            option(
              t.id,
              <>
                <span className="track-name">
                  {t.name}
                  <span className="muted">
                    {clock(t.duration_s)}{t.tags.length > 0 && `, ${t.tags.join(", ")}`}
                  </span>
                </span>
                <AudioPlayer src={t.url} label={t.name} />
              </>,
            ),
          )}
          {option(null, <span className="track-name">Sans musique</span>)}
        </div>
      )}
    </StepPanel>
  );
}
