import { useId, useState } from "react";
import StepPanel, { type PanelProps } from "../StepPanel";
import { locale, t } from "../../i18n";

/** Styles de sous-titres : miroir de `SUBTITLE_STYLES` (backend `services/montage.py`) ; `none` : aucun sous-titre. */
const SUBTITLE_STYLES = [
  { value: "classic", label: t("Contour") },
  { value: "box", label: t("Boîte") },
  { value: "bold", label: t("Gros jaune") },
  { value: "none", label: t("Sans") },
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
    <StepPanel {...props} runLabel={t("Lancer le montage")} onRun={() => flow.run("montage", undefined, { params: { subtitle_style: style } })}>
      <fieldset className="subtitle-styles">
        <legend>{t("Style des sous-titres")}</legend>
        {SUBTITLE_STYLES.map((o) => (
          <label key={o.value} className={`subtitle-style is-${o.value}`}>
            <input type="radio" name={name} checked={style === o.value} onChange={() => setPicked(o.value)} disabled={locked} />
            <span className="subtitle-sample">{o.value !== "none" && t("Ça change tout")}</span>
            <span className="subtitle-name">{o.label}</span>
          </label>
        ))}
      </fieldset>
      {typeof duration === "number" && <p>{t("Durée du rendu : {n} s", { n: duration.toLocaleString(locale) })}</p>}
    </StepPanel>
  );
}
