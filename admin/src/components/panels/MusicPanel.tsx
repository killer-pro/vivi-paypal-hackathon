import AudioPlayer from "../AudioPlayer";
import { useId, useState, type ReactNode } from "react";
import { useApi, type MusicTrack } from "../../api";
import StepPanel, { type PanelProps } from "../StepPanel";
import ImportTrack from "../ImportTrack";
import { ErrorState } from "../ui";
import { clock } from "../../format";
import { useMe } from "../../hooks/useMe";
import { t } from "../../i18n";
import { musicVolume } from "../../montage";

export default function MusicPanel(props: PanelProps) {
  const { flow, step, locked } = props;
  const tracks = useApi<MusicTrack[]>("/music");
  const isAdmin = useMe()?.role === "admin"; // la bibliothèque est commune : seul l'administrateur l'enrichit
  const selected = (step.params.track_id as number | null | undefined) ?? null;
  const choose = (trackId: number | null) => flow.patch("music", { params: { ...step.params, track_id: trackId } });
  const saved = musicVolume(step.params);
  const [dragged, setDragged] = useState<number | null>(null);
  const volume = dragged ?? saved;
  // Enregistré au relâchement du curseur (pas à chaque cran) : le montage devient à refaire.
  const saveVolume = () => {
    if (volume !== saved) flow.patch("music", { params: { ...step.params, volume } });
  };
  const volumeId = useId();

  const option = (id: number | null, children: ReactNode) => (
    <label key={id ?? "none"} className={selected === id ? "track is-chosen" : "track"}>
      <input type="radio" name="track" checked={selected === id} disabled={locked} onChange={() => choose(id)} />
      {children}
    </label>
  );

  return (
    <StepPanel {...props} runLabel={t("Confirmer le choix")}>
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
      {selected !== null && (
        <div className="music-volume">
          <label htmlFor={volumeId}>{t("Volume sous la voix")}</label>
          <input
            id={volumeId}
            type="range"
            min={0}
            max={100}
            step={1}
            value={volume}
            disabled={locked}
            onChange={(e) => setDragged(Number(e.target.value))}
            onPointerUp={saveVolume}
            onKeyUp={saveVolume}
            onBlur={saveVolume}
          />
          <output htmlFor={volumeId}>{volume} %</output>
          <p className="muted">{t("Appliqué à l'aperçu et au prochain montage.")}</p>
        </div>
      )}
      {tracks.error && <ErrorState message={tracks.error} onRetry={tracks.reload} />}
      {!tracks.data && !tracks.error && <p className="muted">{t("Chargement de la bibliothèque…")}</p>}
      {tracks.data && (
        <div className="track-list" role="radiogroup" aria-label={t("Musique de fond")}>
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
          {option(null, <span className="track-name">{t("Sans musique")}</span>)}
        </div>
      )}
    </StepPanel>
  );
}
