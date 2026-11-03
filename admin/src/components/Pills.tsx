import "./Pills.css";

/** Choix exclusif en pastilles (boutons radio). */
export default function Pills<T extends string | number | null>({
  legend,
  name,
  options,
  value,
  onChange,
  disabled,
  hideLegend,
}: {
  legend: string;
  name: string;
  /** `disabled` : choix visible mais non sélectionnable ; `hint` : infobulle (ex. motif du verrou). */
  options: { value: T; label: string; disabled?: boolean; hint?: string }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  /** Légende réservée aux lecteurs d'écran (la rangée se comprend seule). */
  hideLegend?: boolean;
}) {
  return (
    <fieldset className={hideLegend ? "pills pills-bare" : "pills"} disabled={disabled}>
      <legend>{legend}</legend>
      <div className="pills-row">
        {options.map((o) => (
          <label key={o.label} className="pill" title={o.hint}>
            <input type="radio" name={name} checked={o.value === value} disabled={o.disabled} onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
