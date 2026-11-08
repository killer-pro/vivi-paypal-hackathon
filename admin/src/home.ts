import type { ProjectCard } from "./api";
import { STATUS_LABELS, STEP_LABELS, STEP_ORDER, type StepStatus } from "./steps";
import { t } from "./i18n";

export type Segment = "done" | "current" | "todo";

/** Avancement sur les 9 étapes du flow ; `null` = tout est validé. */
export function progress(current: ProjectCard["current_step"]): Segment[] {
  const index = current ? STEP_ORDER.indexOf(current) : STEP_ORDER.length;
  return STEP_ORDER.map((_, i) => (i < index ? "done" : i === index ? "current" : "todo"));
}

/** État affiché sur la carte : `tone` est un statut d'étape (classe `.st-*`), `live` anime la génération auto. */
export function cardState(
  p: Pick<ProjectCard, "status" | "autopilot" | "current_step" | "current_status">,
): { tone: StepStatus; label: string; live?: true } {
  if (p.status === "done" || !p.current_step) return { tone: "approved", label: t("Terminée") };
  const status = p.current_status ?? "pending";
  const step = STEP_LABELS[p.current_step];
  if (status === "failed") return { tone: "failed", label: t("Échec : {step}", { step }) };
  if (p.autopilot) return { tone: "running", label: t("En génération…"), live: true };
  return { tone: status, label: t("{status} : {step}", { status: STATUS_LABELS[status], step }) };
}

export const PAGE_SIZE = 24;

export const SORTS = ["recent", "oldest", "title", "cost"] as const;
export type Sort = (typeof SORTS)[number];
export const SORT_LABELS: Record<Sort, string> = {
  recent: t("Plus récentes"),
  oldest: t("Plus anciennes"),
  title: t("Titre (A à Z)"),
  cost: t("Plus coûteuses"),
};

export type StatusFilter = "" | "draft" | "done";
export const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "", label: t("Toutes") },
  { value: "draft", label: t("En cours") },
  { value: "done", label: t("Terminées") },
];

export interface Library {
  search: string;
  sort: Sort;
  status: StatusFilter;
  /** Nombre de vidéos demandées : « Voir plus » l'augmente d'une page (la liste est rechargée depuis le début). */
  limit: number;
}

/** Chemin de `GET /projects` pour l'état de la bibliothèque ; recherche vide ou filtre « Toutes » omis. */
export function libraryPath({ search, sort, status, limit }: Library): string {
  const params = new URLSearchParams({ sort, limit: String(limit) });
  if (search.trim()) params.set("q", search.trim());
  if (status) params.set("status", status);
  return `/projects?${params}`;
}

/** La bibliothèque est restreinte par une recherche ou un filtre (pas par le tri). */
export function isFiltered({ search, status }: Pick<Library, "search" | "status">): boolean {
  return Boolean(search.trim() || status);
}
