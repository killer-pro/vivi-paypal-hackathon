import { createContext } from "react";
import type { StepName } from "../steps";

/** Durée estimée d'une scène pour une étape (secondes), `null` si le modèle n'en donne pas. Fournie par l'éditeur. */
export const UnitSecondsContext = createContext<(step: StepName) => number | null>(() => null);
