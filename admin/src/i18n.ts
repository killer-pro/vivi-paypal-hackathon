import { en } from "./locales/en";

export type Lang = "fr" | "en";

const STORAGE_KEY = "vivi.lang";
const LANGS: readonly Lang[] = ["fr", "en"];

function stored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // stockage bloqué : on reste sur le français
  }
}

/** Langue de l'interface : `?lang=` dans l'adresse (mémorisée), sinon le dernier choix, sinon le français. */
function detect(): Lang {
  const asked = new URLSearchParams(globalThis.location?.search).get("lang");
  if (LANGS.includes(asked as Lang)) {
    try {
      localStorage.setItem(STORAGE_KEY, asked!);
    } catch {
      // sans stockage, le paramètre seul décide pour cette session
    }
    return asked as Lang;
  }
  const saved = stored();
  return LANGS.includes(saved as Lang) ? (saved as Lang) : "fr";
}

/** Fixée au chargement : changer de langue recharge la page (les libellés calculés à l'import suivent ainsi). */
export const lang: Lang = detect();
if (typeof document !== "undefined") document.documentElement.lang = lang;
export const locale = lang === "en" ? "en-US" : "fr-FR";

export function setLang(next: Lang) {
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // le rechargement reprend alors la langue de l'adresse ou le français
  }
  const url = new URL(location.href);
  url.searchParams.delete("lang");
  location.assign(url);
}

/** Traduit un texte écrit en français (la clé *est* le français) ; `{nom}` est remplacé par `vars.nom`.
 *  Un texte absent du dictionnaire reste en français. */
export function t(fr: string, vars?: Record<string, string | number>): string {
  const text = lang === "en" ? (en[fr] ?? fr) : fr;
  return vars ? text.replace(/\{(\w+)\}/g, (whole, name) => String(vars[name] ?? whole)) : text;
}

/** Singulier si `n` ≤ 1, sinon pluriel ; les deux formes contiennent `{n}` et sont des clés du dictionnaire. */
export function tn(n: number, one: string, many: string): string {
  return t(n > 1 ? many : one, { n: n.toLocaleString(locale) });
}
