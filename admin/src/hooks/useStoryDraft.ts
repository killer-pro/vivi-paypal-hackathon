import { patchByKey } from "../assist";
import { moved, withoutAt } from "../plan";
import {
  blankBeat,
  newBeat,
  newElement,
  storyOf,
  storyTotal,
  toResult,
  unknownIds,
  withoutElement,
  type DraftBeat,
  type StoryElement,
} from "../story";
import type { Step } from "../steps";
import { useDraft } from "./useDraft";
import type { Flow } from "./useProject";

/** Brouillon de l'histoire (fiche visuelle, éléments suivis, beats) partagé par l'écran Plan et l'éditeur. */
export function useStoryDraft(step: Step) {
  const draft = useDraft(storyOf(step.result));
  const story = draft.value;
  const setBeats = (beats: DraftBeat[]) => draft.update((prev) => ({ ...prev, beats }));

  return {
    story,
    dirty: draft.dirty,
    total: storyTotal(story.beats),
    unknown: unknownIds(story),
    blank: blankBeat(story.beats),
    setBible: (bible: string) => draft.update((prev) => ({ ...prev, bible })),
    updateBeat: (key: string, patch: Partial<DraftBeat>) =>
      draft.update((prev) => ({ ...prev, beats: patchByKey(prev.beats, key, patch) })),
    moveBeat: (i: number, by: number) => setBeats(moved(story.beats, i, by)),
    addBeat: () => setBeats([...story.beats, newBeat()]),
    removeBeat: (i: number) => setBeats(withoutAt(story.beats, i)),
    updateElement: (id: string, patch: Partial<StoryElement>) =>
      draft.update((prev) => ({ ...prev, elements: prev.elements.map((e) => (e.id === id ? { ...e, ...patch } : e)) })),
    addElement: (name: string) =>
      draft.update((prev) => ({ ...prev, elements: [...prev.elements, newElement(name, prev.elements)] })),
    removeElement: (id: string) => draft.update((prev) => withoutElement(prev, id)),
    /** Montre ou retire un élément dans un beat ; `state` : son état quand il y est. */
    setPresence: (key: string, id: string, state: string | null) =>
      draft.update((prev) => ({
        ...prev,
        beats: prev.beats.map((b) =>
          b.key !== key
            ? b
            : {
                ...b,
                elements:
                  state === null
                    ? b.elements.filter((e) => e.id !== id)
                    : b.elements.some((e) => e.id === id)
                      ? b.elements.map((e) => (e.id === id ? { ...e, state } : e))
                      : [...b.elements, { id, state }],
              },
        ),
      })),
    reset: draft.reset,
    async save(flow: Flow): Promise<boolean> {
      const saved = await flow.patch("story", { result: toResult(story, step.result) });
      if (saved) draft.reset();
      return Boolean(saved);
    },
  };
}
