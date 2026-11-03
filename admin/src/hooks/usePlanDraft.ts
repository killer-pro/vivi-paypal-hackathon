import { patchByKey } from "../assist";
import { firstBlank, moved, newScene, planTotal, toDraft, withoutAt, type DraftScene } from "../plan";
import type { ProjectDetail } from "../api";
import type { Step } from "../steps";
import type { Flow } from "./useProject";
import { useDraft } from "./useDraft";

/** Brouillon du plan (scènes et fiche visuelle) partagé par l'onglet Script de l'éditeur et l'écran Plan. */
export function usePlanDraft(project: ProjectDetail, step: Step) {
  const scenes = useDraft<DraftScene[]>(toDraft(project.scenes));
  const savedBible = typeof step.result?.bible === "string" ? step.result.bible : "";
  const bible = useDraft(savedBible);
  const list = scenes.value;

  const reset = () => {
    scenes.reset();
    bible.reset();
  };

  return {
    list,
    bible,
    dirty: scenes.dirty || bible.dirty,
    total: planTotal(list),
    // L'API refuse (422) un texte vide ou fait d'espaces : on le signale avant l'envoi.
    blank: firstBlank(list),
    // Ordre du brouillon identique à l'enregistré : sinon l'enchaînement d'une carte (relatif à la scène précédente
    // enregistrée) serait faux et reste masqué jusqu'à l'enregistrement.
    ordered: list.map((s) => s.id).join() === project.scenes.map((s) => s.id).join(),
    // Par clé et en mise à jour fonctionnelle : une réponse tardive de l'assistant vise la bonne scène et n'écrase pas
    // les modifications faites entre-temps (autres champs, réordonnancement, suppression).
    update: (key: string, patch: Partial<DraftScene>) => scenes.update((prev) => patchByKey(prev, key, patch)),
    move: (i: number, by: number) => scenes.set(moved(list, i, by)),
    add: () => scenes.set([...list, newScene()]),
    remove: (i: number) => scenes.set(withoutAt(list, i)),
    reset,
    async save(flow: Flow): Promise<boolean> {
      const saved = await flow.patch("script", {
        scenes: list.map(({ key: _key, ...s }) => s),
        result: { ...step.result, bible: bible.value.trim() },
      });
      if (saved) reset();
      return Boolean(saved);
    },
  };
}
