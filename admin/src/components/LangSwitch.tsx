import { lang, setLang, t, type Lang } from "../i18n";
import "./LangSwitch.css";

const LANGS: { id: Lang; label: string }[] = [
  { id: "fr", label: "FR" },
  { id: "en", label: "EN" },
];

/** Bascule français / anglais de l'interface : le choix est mémorisé et la page se recharge dans la nouvelle langue. */
export default function LangSwitch() {
  return (
    <div className="lang-switch" role="group" aria-label={t("Langue")}>
      {LANGS.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          className="lang-option"
          aria-pressed={id === lang}
          onClick={() => id !== lang && setLang(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
