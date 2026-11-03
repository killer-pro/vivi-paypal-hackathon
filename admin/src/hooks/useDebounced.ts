import { useEffect, useState } from "react";

/** Valeur qui ne suit `value` qu'après `ms` sans changement (saisie de recherche : une requête par pause, pas par frappe). */
export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}
