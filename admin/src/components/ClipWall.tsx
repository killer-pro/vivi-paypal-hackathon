import { useEffect, useRef } from "react";
import { clip, WALL } from "../landing";
import { reducedMotion } from "../motion";
import "./ClipWall.css";

/** Clip vertical en boucle, lu seulement quand il est à l'écran ; l'affiche seule si le visiteur veut moins de mouvement. */
export function Clip({ name }: { name: string }) {
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const el = video.current;
    if (!el || reducedMotion()) return;
    const watcher = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) void el.play().catch(() => undefined);
      else el.pause();
    });
    watcher.observe(el);
    return () => watcher.disconnect();
  }, []);

  return <video ref={video} src={clip(name, "mp4")} poster={clip(name, "jpg")} muted loop playsInline preload="none" />;
}

/** Fond décoratif de l'accroche et des écrans de compte : le parent doit être `position: relative` et poser son voile. */
export default function ClipWall() {
  return (
    <div className="clip-wall" aria-hidden>
      {WALL.map((column, i) => (
        <div key={i} className="clip-wall-col" style={{ "--i": i } as React.CSSProperties}>
          {[...column, ...column].map((name, k) => (
            <div key={k} className="clip-wall-clip">
              <Clip name={name} />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
