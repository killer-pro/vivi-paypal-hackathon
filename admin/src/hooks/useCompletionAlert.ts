import { useEffect, useRef } from "react";
import { completionMessage } from "../studio";
import type { Step } from "../steps";

const BASE_TITLE = document.title;

/** Demande l'autorisation de notifier ; à appeler depuis un geste de l'utilisateur (lancement d'une génération). */
export function requestNotificationPermission(): void {
  if ("Notification" in window && Notification.permission === "default") void Notification.requestPermission();
}

/**
 * Une génération longue (jusqu'à 18 min en local) se termine pendant qu'on est ailleurs : quand une étape quitte
 * `running`, l'onglet le dit dans son titre (retiré au retour) et, si c'est autorisé, par une notification.
 */
export function useCompletionAlert(projectTitle: string | undefined, steps: Step[] | undefined): void {
  const previous = useRef<Step[] | undefined>(undefined);

  useEffect(() => {
    const message = steps && completionMessage(previous.current, steps);
    previous.current = steps;
    if (!message || !document.hidden) return;
    document.title = `${message} · ${BASE_TITLE}`;
    if ("Notification" in window && Notification.permission === "granted")
      new Notification(projectTitle ?? BASE_TITLE, { body: message });
  }, [projectTitle, steps]);

  useEffect(() => {
    const restore = () => {
      if (!document.hidden) document.title = BASE_TITLE;
    };
    document.addEventListener("visibilitychange", restore);
    return () => {
      document.removeEventListener("visibilitychange", restore);
      document.title = BASE_TITLE;
    };
  }, []);
}
