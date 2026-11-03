import { useEffect, useRef } from "react";
import type { Step } from "../../steps";
import { TOOL_STATE_LABELS, TOOLS, toolState, type Tool, type ToolId, type ToolState } from "../../studio";

/** Couleur de la pastille : classe de statut `.st-*` (voir index.css). */
const TONE: Record<ToolState, Step["status"]> = {
  todo: "pending",
  running: "running",
  awaiting: "awaiting_validation",
  approved: "approved",
  failed: "failed",
};

/** Frise des étapes de la vidéo, dans l'ordre de production : pastille de statut et libellé. */
export default function Pipeline({
  steps,
  selected,
  onSelect,
}: {
  steps: Step[];
  selected: ToolId;
  onSelect: (tool: Tool) => void;
}) {
  const nav = useRef<HTMLElement>(null);
  // Sur mobile la frise défile : l'étape affichée reste visible.
  useEffect(() => {
    nav.current?.querySelector('[aria-current="step"]')?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [selected]);

  return (
    <nav className="pipeline" aria-label="Étapes de la vidéo" ref={nav}>
      <ol>
        {TOOLS.map((tool) => {
          const state = toolState(tool, steps);
          return (
            <li key={tool.id}>
              <button
                className={`stage st-${TONE[state]}`}
                aria-current={tool.id === selected ? "step" : undefined}
                aria-label={`${tool.label}, ${TOOL_STATE_LABELS[state]}`}
                title={`${tool.label} : ${TOOL_STATE_LABELS[state]}`}
                onClick={() => onSelect(tool)}
              >
                <i className={`stage-mark is-${state}`} aria-hidden />
                {tool.label}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
