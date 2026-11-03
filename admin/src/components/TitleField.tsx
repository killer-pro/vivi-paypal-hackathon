import { useDraft } from "../hooks/useDraft";

/** Titre éditable en place : Entrée ou sortie du champ enregistre, Échap annule ; un titre vide est refusé. */
export default function TitleField({ title, onRename, locked }: { title: string; onRename: (t: string) => Promise<boolean>; locked: boolean }) {
  const draft = useDraft(title);
  const commit = async () => {
    const next = draft.value.trim();
    if (!next || next === title) return draft.reset();
    if (await onRename(next)) draft.reset();
  };
  return (
    <input
      className="title-field"
      aria-label="Titre du projet"
      maxLength={200}
      value={draft.value}
      readOnly={locked}
      onChange={(e) => draft.set(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          draft.reset();
          requestAnimationFrame(() => (e.target as HTMLInputElement).blur());
        }
      }}
    />
  );
}
