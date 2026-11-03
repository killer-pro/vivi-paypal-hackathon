import { MAX_THEME } from "./limits";

// Idée saisie dans la barre de la page « Découvrir » avant d'avoir un compte : gardée dans le navigateur (et non la
// session) pour survivre au lien de confirmation e-mail, ouvert dans un autre onglet, puis préremplir `/new`.
const KEY = "vivi.idee";

/** Stockage minimal attendu (celui du navigateur, ou un faux dans les tests). */
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const browserStore = (): Store | null => {
  try {
    return window.localStorage;
  } catch {
    return null; // fenêtre privée ou données de site bloquées
  }
};

/** Idée prête à envoyer : sans espaces autour, coupée à la limite du champ ; `null` si elle est vide. */
export function cleanIdea(text: string): string | null {
  return text.trim().slice(0, MAX_THEME) || null;
}

/** Mémorise l'idée ; sans effet si elle est vide ou si le stockage est indisponible. */
export function rememberIdea(text: string, store: Store | null = browserStore()) {
  const idea = cleanIdea(text);
  if (!idea) return;
  try {
    store?.setItem(KEY, idea);
  } catch {
    // quota ou stockage refusé : l'idée sera à ressaisir
  }
}

/** Idée mémorisée, sans l'effacer (les écrans de compte en ont besoin avant la création de la vidéo). */
export function pendingIdea(store: Store | null = browserStore()): string | null {
  try {
    return store?.getItem(KEY) ?? null;
  } catch {
    return null;
  }
}

/** Efface l'idée mémorisée, une fois la vidéo créée. */
export function forgetIdea(store: Store | null = browserStore()) {
  try {
    store?.removeItem(KEY);
  } catch {
    // rien à effacer
  }
}
