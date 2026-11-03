import { createContext, useContext } from "react";
import type { Me } from "../auth";

/** Compte connecté, fourni par `Layout` après `GET /auth/me` (null hors des écrans connectés). */
export const MeContext = createContext<Me | null>(null);

export function useMe(): Me | null {
  return useContext(MeContext);
}
