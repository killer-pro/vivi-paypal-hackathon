import { useEffect, useLayoutEffect, useRef } from "react";
import { api } from "./api";
import type { StepName, StepStatus } from "./steps";

export interface StepEvent {
  project_id: number;
  step: StepName;
  status: StepStatus;
  error: string | null;
}

/** S'abonne au flux SSE `/api/events`. */
export function useEvents(onEvent: (e: StepEvent) => void): void {
  const handler = useRef(onEvent);
  useLayoutEffect(() => {
    handler.current = onEvent;
  });

  useEffect(() => {
    const source = new EventSource("/api/events", { withCredentials: true });
    source.onmessage = (msg) => {
      let event: StepEvent;
      try {
        event = JSON.parse(msg.data);
      } catch {
        return; // charge utile illisible : ignorée
      }
      handler.current(event);
    };
    // Coupure réseau : EventSource se reconnecte seul (CONNECTING). Refus du serveur (ex. session expirée) : flux
    // fermé définitivement ; on revérifie la session, `api` redirige vers /login sur 401.
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) api("/auth/me").catch(() => undefined);
    };
    return () => source.close();
  }, []);
}
