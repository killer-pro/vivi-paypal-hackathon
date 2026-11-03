import { useSyncExternalStore } from "react";

/** Vrai tant que la requête média correspond (suit les changements de taille de la fenêtre). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", notify);
      return () => list.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
  );
}
