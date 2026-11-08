import { useEffect, useRef, useState } from "react";
import { clock } from "../format";
import { PauseIcon, PlayIcon } from "./icons";
import "./AudioPlayer.css";
import { t } from "../i18n";

/** Lecteur en cours : une seule piste joue à la fois dans la page. */
let current: HTMLAudioElement | null = null;

/** Lecteur audio compact (lecture, barre de progression, temps) : remplace les contrôles natifs du navigateur. */
export default function AudioPlayer({ src, label, className }: { src: string; label: string; className?: string }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    const el = audio.current;
    return () => {
      el?.pause();
      if (current === el) current = null;
    };
  }, []);

  function toggle() {
    const el = audio.current;
    if (!el) return;
    if (!el.paused) return el.pause();
    if (current && current !== el) current.pause();
    current = el;
    void el.play();
  }

  return (
    <div className={className ? `audio-player ${className}` : "audio-player"}>
      <audio
        ref={audio}
        src={src}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onEnded={() => setTime(0)}
      />
      <button type="button" className="audio-play" onClick={toggle} aria-label={t("{action} : {label}", { action: playing ? t("Mettre en pause") : t("Écouter"), label })}>
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>
      <input
        className="audio-seek"
        type="range"
        min={0}
        max={duration || 1}
        step="any"
        value={time}
        disabled={!duration}
        aria-label={`Position : ${label}`}
        style={{ "--progress": `${duration ? (time / duration) * 100 : 0}%` } as React.CSSProperties}
        onChange={(e) => {
          if (audio.current) audio.current.currentTime = Number(e.target.value);
        }}
      />
      <span className="audio-time">{clock(time)}</span>
    </div>
  );
}
