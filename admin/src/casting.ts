import { referenceElements, referenceImage, scenesUsing, type ProjectDetail, type Scene } from "./api";

export type CastKind = "character" | "prop" | "place";
/** `none` : élément de l'histoire sans image prévue (lieu, accessoire au-delà du plafond). */
export type CastStatus = "ready" | "generating" | "failed" | "missing" | "none";

/** Un élément récurrent de la vidéo (personnage, accessoire, lieu), son image et les scènes où il apparaît. */
export interface CastMember {
  id: string;
  name: string;
  kind: CastKind;
  status: CastStatus;
  imageUrl?: string;
  scenes: number[];
}

const STEP_STATUS: Record<string, CastStatus> = { running: "generating", failed: "failed" };

/** Casting du projet : éléments de l'histoire, puis ceux qui n'existent que dans les références du script (accessoires). */
export function castOf(project: Pick<ProjectDetail, "steps" | "scenes" | "assets">): CastMember[] {
  const story = project.steps.find((s) => s.name === "story")?.result?.elements;
  const described = (Array.isArray(story) ? story : []) as { id: string; kind?: CastKind; name?: string }[];
  const planned = new Set(referenceElements(project.steps).map((r) => r.id));
  const ids = new Set([...described.map((e) => e.id), ...planned]);
  const stepStatus = project.steps.find((s) => s.name === "reference")?.status ?? "pending";
  const byId = new Map(described.map((e) => [e.id, e]));

  return [...ids].map((id) => {
    const image = referenceImage(project.assets, id);
    const status: CastStatus = image ? "ready" : !planned.has(id) ? "none" : (STEP_STATUS[stepStatus] ?? "missing");
    const element = byId.get(id);
    return {
      id,
      name: element?.name || id,
      kind: element?.kind ?? "prop",
      status,
      ...(image && { imageUrl: image.url }),
      scenes: scenesUsing(project.scenes, id),
    };
  });
}

/** Lien d'une scène avec la précédente : `from` est la position de la scène dont on reprend la dernière image. */
export interface SceneLink {
  kind: "cut" | "chain";
  from?: number;
}

/** `null` pour la première scène (et hors de la liste). */
export function sceneLink(scenes: Pick<Scene, "position" | "continuity">[], index: number): SceneLink | null {
  if (index <= 0 || index >= scenes.length) return null;
  return scenes[index].continuity === "continue" ? { kind: "chain", from: scenes[index - 1].position } : { kind: "cut" };
}

/** Éléments visibles dans la scène, dans son ordre, avec leur état ; un id absent du casting est ignoré. */
export function sceneElements(scene: Pick<Scene, "elements">, cast: CastMember[]): { member: CastMember; state: string }[] {
  const byId = new Map(cast.map((m) => [m.id, m]));
  return scene.elements.flatMap((e) => {
    const member = byId.get(e.id);
    return member ? [{ member, state: e.state }] : [];
  });
}
