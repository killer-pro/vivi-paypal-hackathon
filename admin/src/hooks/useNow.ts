import { useEffect, useState } from "react";

/** Heure courante (ms), rafraîchie toutes les `intervalMs` : pour un compteur de temps écoulé. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
