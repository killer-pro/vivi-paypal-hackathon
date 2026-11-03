/** Réglages éditables de `GET/PUT /api/settings` (secrets renvoyés masqués : `••••` + 4 derniers caractères). */
export type Settings = Record<string, string>;

const MASK = "••••";
export const SECRET_KEYS = new Set(["anthropic_api_key", "gemini_api_key", "fal_key", "elevenlabs_api_key", "langfuse_secret_key"]);

/**
 * Corps du `PUT /settings` : seulement les champs modifiés. Un secret se saisit dans un champ vide (vide = inchangé) ;
 * une valeur masquée n'est jamais renvoyée.
 */
export function settingsBody(saved: Settings, draft: Settings): Settings {
  const body: Settings = {};
  for (const [key, raw] of Object.entries(draft)) {
    const value = raw.trim();
    const changed = SECRET_KEYS.has(key) ? value !== "" && !value.startsWith(MASK) : value !== saved[key];
    if (changed) body[key] = value;
  }
  return body;
}

/** Options d'un `<select>` : la valeur enregistrée reste choisissable même si elle n'est plus proposée. */
export function withCurrent(options: string[], current: string): string[] {
  return !current || options.includes(current) ? options : [current, ...options];
}

export interface Voice {
  id: string;
  name: string;
}

/** Catalogue de voix du réglage `voice_catalog` (JSON) ; vide si le réglage est absent ou illisible. */
export function parseVoices(raw: string | undefined): Voice[] {
  try {
    const voices: unknown = JSON.parse(raw || "[]");
    return Array.isArray(voices) ? (voices as Voice[]) : [];
  } catch {
    return [];
  }
}

/** Libellé d'une voix dans une liste de choix : son nom, ou son identifiant si elle n'est plus au catalogue. */
export function voiceLabel(voices: Voice[], id: string): string {
  return voices.find((v) => v.id === id)?.name ?? id;
}
