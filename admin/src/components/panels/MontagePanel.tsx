import { useId, useState } from "react";
import StepPanel, { type PanelProps } from "../StepPanel";

/** Styles de sous-titres : miroir de `SUBTITLE_STYLES` (backend `services/montage.py`). */
const SUBTITLE_STYLES = [
  { value: "classic", label: "Contour" },
  { value: "box", label: "Boîte" },
  { value: "bold", label: "Gros jaune" },
] as const;
const DEFAULT_STYLE = "classic";

/** Montage : style des sous-titres, puis rendu ; le rendu se regarde dans l'aperçu central. */
export default function MontagePanel(props: PanelProps) {
  const { flow, step, locked } = props;
  const duration = step.result?.duration_s;
  const saved = String(step.params.subtitle_style ?? DEFAULT_STYLE);
  const [picked, setPicked] = useState<string | null>(null);
  const style = picked ?? saved;
  const name = useId();

  return (
    <StepPanel {...props} runLabel="Lancer le montage" onRun={() => flow.run("montage", undefined, { params: { subtitle_style: style } })}>
      <fieldset className="subtitle-styles">
        <legend>Style des sous-titres</legend>
        {SUBTITLE_STYLES.map((o) => (
          <label key={o.value} className={`subtitle-style is-${o.value}`}>
            <input type="radio" name={name} checked={style === o.value} onChange={() => setPicked(o.value)} disabled={locked} />
            <span className="subtitle-sample">Ça change tout</span>
            <span className="subtitle-name">{o.label}</span>
          </label>
        ))}
      </fieldset>
      {typeof duration === "number" && <p>Durée du rendu : {duration.toLocaleString("fr-FR")} s</p>}
    </StepPanel>
  );
}
