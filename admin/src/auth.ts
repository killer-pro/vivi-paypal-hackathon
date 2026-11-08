import { t } from "./i18n";
/** Compte connecté (`GET /auth/me`). */
export type Me = { id: number; email: string; role: "user" | "admin"; email_verified: boolean; subscribed: boolean; subscription_ends_at: string | null };

/** Mêmes bornes que le backend (`app/security.py`). */
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
export const PASSWORD_RULE = t("Le mot de passe doit compter de {min} à {max} caractères", { min: PASSWORD_MIN, max: PASSWORD_MAX });

/** Écrans accessibles sans session : un 401 n'y renvoie pas vers `/login`. */
const PUBLIC_PATHS = new Set(["/decouvrir", "/login", "/register", "/verify", "/forgot", "/reset"]);

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname);
}

/** Entrées de navigation visibles pour ce rôle : celles marquées `adminOnly` sont réservées à l'administrateur. */
export function visibleNav<T extends { adminOnly?: boolean }>(items: T[], role: Me["role"]): T[] {
  return role === "admin" ? items : items.filter((i) => !i.adminOnly);
}

/** Jeton des liens reçus par e-mail (`?token=…`) ; null s'il manque ou est vide. */
export function tokenFromSearch(search: string): string | null {
  return new URLSearchParams(search).get("token") || null;
}

export function validPassword(password: string): boolean {
  return password.length >= PASSWORD_MIN && password.length <= PASSWORD_MAX;
}
