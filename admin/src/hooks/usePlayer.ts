import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { SceneTiming } from "../montage";
import { sceneAt, type Block } from "../studio";

/** Écart minimal entre deux mises à jour du temps affiché (l'horloge tourne à chaque image). */
const TIME_STEP_S = 0.05;
/** Reprise d'une scène terminée : à moins de cet écart de sa fin, `play` la rejoue depuis le début. */
const END_SLACK_S = 0.05;

interface PlayerSource {
  /** Rendu final : une seule vidéo couvre toute la timeline. */
  render?: string;
  /** Sans rendu : clip choisi et voix de la scène `index`, joués ensemble, puis scène suivante. */
  clip?: string;
  voice?: string;
  /** Musique de fond choisie : joue en continu sur la timeline, sous les scènes (le rendu la contient déjà). */
  music?: string;
  /** Niveau de la musique sous la voix (0 à 1), le même que dans le rendu. */
  musicVolume: number;
  blocks: Block[];
  /** Calage de chaque scène (durée, vitesse de la voix et du clip), comme le montage ; un par bloc. */
  timings: SceneTiming[];
  total: number;
  index: number;
  setIndex: (i: number) => void;
}

/**
 * Lecteur de l'aperçu, piloté par la timeline (temps en secondes de timeline). Avec le rendu, une seule vidéo ; la
 * scène sélectionnée suit la tête de lecture. Sans rendu, une horloge fait avancer la scène : clip et voix y jouent aux
 * vitesses du montage (voix accélérée ou ralentie, clip étiré), la scène suivante démarre quand sa durée est écoulée,
 * jamais avant la fin de la voix, et l'horloge attend un média qui charge encore.
 */
export function usePlayer({ render, clip, voice, music, musicVolume, blocks, timings, total, index, setIndex }: PlayerSource) {
  const video = useRef<HTMLVideoElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const musicAudio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  // Lecture à reprendre quand la source change (scène suivante, ou scène choisie pendant la lecture).
  const resume = useRef(false);
  // Secondes écoulées dans la scène jouée (sans rendu).
  const elapsed = useRef(0);
  const block = blocks[index];

  /** Secondes de timeline par seconde de rendu. */
  const scale = () => {
    const d = video.current?.duration;
    return d && Number.isFinite(d) && total ? total / d : 1;
  };

  /** Place la musique à `t` secondes de timeline (elle ne redémarre pas à chaque scène). */
  const syncMusic = (t: number) => {
    const m = musicAudio.current;
    if (m) m.currentTime = Number.isFinite(m.duration) && m.duration > 0 ? t % m.duration : t; // piste plus courte : elle boucle
  };

  /** Place clip et voix de la scène à `t` secondes écoulées, aux vitesses du montage. */
  const place = (t: number) => {
    const { rate = 1, tempo = 1 } = timings[index] ?? {};
    elapsed.current = t;
    const v = video.current;
    if (v) {
      v.defaultPlaybackRate = v.playbackRate = rate;
      v.currentTime = t * rate;
    }
    const a = audio.current;
    if (a) {
      a.defaultPlaybackRate = a.playbackRate = tempo;
      a.preservesPitch = true;
      a.currentTime = t * tempo;
    }
  };

  const play = () => {
    const v = video.current;
    if (render) {
      if (v?.ended) v.currentTime = 0;
      v?.play().catch(() => undefined); // source absente ou illisible : rien ne se passe
      return;
    }
    if (!block) return;
    const t = elapsed.current >= block.duration - END_SLACK_S ? 0 : elapsed.current;
    place(t);
    if (musicAudio.current?.paused) syncMusic(block.start + t);
    audio.current?.play().catch(() => undefined);
    musicAudio.current?.play().catch(() => undefined);
    v?.play().catch(() => undefined);
    setPlaying(true);
  };

  const pause = () => {
    video.current?.pause();
    audio.current?.pause();
    musicAudio.current?.pause();
    setPlaying(false);
  };

  useEffect(() => {
    if (musicAudio.current) musicAudio.current.volume = musicVolume;
  }, [music, musicVolume, render]); // l'élément audio n'existe que sans rendu

  const resumeAfterSourceChange = useEffectEvent(() => {
    if (!resume.current) return;
    resume.current = false;
    play();
  });
  useEffect(() => resumeAfterSourceChange(), [index, clip, voice]);

  const advance = useEffectEvent(() => {
    if (index >= blocks.length - 1) return pause();
    video.current?.pause();
    audio.current?.pause();
    resume.current = true;
    elapsed.current = 0;
    setIndex(index + 1);
    setTime(blocks[index + 1].start);
  });

  // Horloge de la scène jouée sans rendu : elle n'avance pas tant qu'un média charge. Dépend des valeurs du bloc, pas de
  // l'objet (recréé à chaque rendu) : elle ne repart pas à chaque mise à jour du temps affiché.
  const start = block?.start;
  const duration = block?.duration;
  useEffect(() => {
    if (render || !playing || start === undefined || duration === undefined) return;
    let frame = 0;
    let last = performance.now();
    let shown = elapsed.current;
    const tick = (now: number) => {
      const loading = [video.current, audio.current].some((m) => m && !m.error && m.currentSrc && m.readyState < 2);
      if (!loading) elapsed.current += (now - last) / 1000;
      last = now;
      if (elapsed.current >= duration) return advance();
      if (elapsed.current - shown >= TIME_STEP_S) {
        shown = elapsed.current;
        const t = start + elapsed.current;
        setTime(t);
        const m = musicAudio.current;
        if (m && !m.paused && Math.abs(m.currentTime - (m.duration ? t % m.duration : t)) > 0.5) syncMusic(t); // dérive : la musique suit la timeline
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // `syncMusic` ne dépend que des refs
  }, [render, playing, index, start, duration]);

  /** Sélectionne une scène : le rendu s'y place, sinon son clip devient la source. */
  const select = (i: number) => {
    const target = blocks[i];
    if (!target) return;
    setIndex(i);
    setTime(target.start);
    elapsed.current = 0;
    if (render) {
      if (video.current) video.current.currentTime = target.start / scale();
    } else if (i === index) {
      place(0);
      syncMusic(target.start);
    } else {
      syncMusic(target.start);
      if (playing) resume.current = true;
    }
  };

  const seek = (t: number) => {
    if (render && video.current) {
      video.current.currentTime = t / scale();
      setTime(t);
    } else {
      select(sceneAt(blocks, t));
    }
  };

  // Avec le rendu, la vidéo pilote le temps ; sans lui, l'horloge ci-dessus (le clip peut finir avant la scène).
  const handlers = {
    onPlay: () => render && setPlaying(true),
    onPause: () => render && setPlaying(false),
    onTimeUpdate: () => {
      const v = video.current;
      if (!v || !render) return;
      const t = v.currentTime * scale();
      setTime(t);
      const i = sceneAt(blocks, t);
      if (i >= 0 && i !== index) setIndex(i);
    },
  };

  return { video, audio, musicAudio, playing, time, toggle: () => (playing ? pause() : play()), select, seek, handlers };
}

export type Player = ReturnType<typeof usePlayer>;
