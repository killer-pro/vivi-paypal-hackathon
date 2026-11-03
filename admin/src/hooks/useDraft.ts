import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";

/** Reçoit l'état « modifié non enregistré » de chaque brouillon monté (fourni par l'éditeur). */
export const DirtyDraftsContext = createContext<((id: string, dirty: boolean) => void) | null>(null);

/**
 * Brouillon local d'une valeur serveur : tant qu'on ne l'édite pas, `value` suit la source (rafraîchie par SSE) ;
 * dès la première modification, elle est figée jusqu'à `reset` (après enregistrement ou annulation).
 * `dirty` : le brouillon diffère de la source ; signalé à `DirtyDraftsContext` pour prévenir avant de quitter l'étape.
 * `update(fn)` : mise à jour fonctionnelle à partir du brouillon le plus récent (réponse asynchrone, ex. assistant IA,
 * qui ne doit pas écraser les autres modifications faites pendant l'attente).
 */
export function useDraft<T>(source: T) {
  const [draft, setDraft] = useState<T | null>(null);
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(source);
  const id = useId();
  const report = useContext(DirtyDraftsContext);
  const latestSource = useRef(source);
  useEffect(() => {
    latestSource.current = source;
  });
  const update = useCallback((fn: (prev: T) => T) => setDraft((prev) => fn(prev ?? latestSource.current)), []);

  useEffect(() => {
    report?.(id, dirty);
    return () => report?.(id, false);
  }, [report, id, dirty]);

  return { value: draft ?? source, dirty, set: setDraft, update, reset: () => setDraft(null) };
}

/**
 * Suivi des brouillons modifiés montés sous `DirtyDraftsContext.Provider value={report}`. `hasDirty()` se lit au
 * moment d'agir (changer d'étape) ; fermer ou recharger l'onglet avec un brouillon modifié demande confirmation.
 */
export function useDirtyDrafts() {
  const dirty = useRef(new Set<string>());
  const report = useCallback((id: string, isDirty: boolean) => {
    if (isDirty) dirty.current.add(id);
    else dirty.current.delete(id);
  }, []);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty.current.size > 0) e.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  return { report, hasDirty: () => dirty.current.size > 0 };
}
