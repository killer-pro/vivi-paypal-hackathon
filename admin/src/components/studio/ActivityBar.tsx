import { useEffect, useId, useRef, useState } from "react";
import type { QueuedRun, Scene } from "../../api";
import { queueLabel, type Activity } from "../../studio";
import GenerationTiming from "../GenerationTiming";
import { ChevronDownIcon, CloseIcon, StopIcon } from "../icons";

/**
 * Bandeau des générations en cours, visible quelle que soit l'étape ou la scène affichée : ce qui travaille, où, et de
 * quoi aller le voir ou l'arrêter. Les demandes en file d'attente se déplient sous le bandeau, dans l'ordre de départ,
 * et se retirent une à une. Absent quand rien ne tourne ni n'attend.
 */
export default function ActivityBar({
  activities,
  busy,
  onShow,
  onStop,
  queue,
  scenes,
  onUnqueue,
}: {
  activities: Activity[];
  busy: boolean;
  onShow: (activity: Activity) => void;
  onStop: (activity: Activity) => void;
  queue: QueuedRun[];
  scenes: Pick<Scene, "id" | "position">[];
  onUnqueue: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const listId = useId();
  const expanded = open && queue.length > 0;

  useEffect(() => {
    if (!expanded) return;
    const close = (e: PointerEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menu.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [expanded]);

  if (activities.length === 0 && queue.length === 0) return null;
  return (
    <div className="activity-bar" role="status">
      {activities.map((a) => (
        <div className="activity" key={a.step}>
          <span className="spinner" aria-hidden />
          <span className="activity-text">
            <strong>{a.label}</strong> : {a.detail}
          </span>
          <GenerationTiming step={a.source} />
          <button className="btn btn-small btn-ghost" onClick={() => onShow(a)}>
            Voir
          </button>
          <button className="btn btn-small btn-ghost" onClick={() => onStop(a)} disabled={busy}>
            <StopIcon /> Arrêter
          </button>
        </div>
      ))}
      {queue.length > 0 && (
        <div className="queue" ref={menu}>
          <button
            className="btn btn-small btn-ghost queue-toggle"
            aria-expanded={expanded}
            aria-controls={listId}
            onClick={() => setOpen((o) => !o)}
          >
            {queue.length} en attente <ChevronDownIcon />
          </button>
          {expanded && (
            <ol className="queue-pop" id={listId}>
              {queue.map((item) => (
                <li key={item.id}>
                  <span className="queue-item">{queueLabel(item, scenes)}</span>
                  <button
                    className="btn btn-ghost btn-icon btn-small"
                    title="Retirer de la file"
                    aria-label={`Retirer ${queueLabel(item, scenes)} de la file`}
                    onClick={() => onUnqueue(item.id)}
                    disabled={busy}
                  >
                    <CloseIcon />
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
