import { useContext } from "react";
import { durationText } from "../format";
import { useNow } from "../hooks/useNow";
import type { Step } from "../steps";
import { generationTiming } from "../studio";
import { UnitSecondsContext } from "./unitSeconds";

/** Temps restant arrondi à l'excès (5 s, puis 30 s au-delà de 5 min) : le chiffre ne saute pas à chaque seconde. */
const rounded = (seconds: number) => Math.ceil(seconds / (seconds > 300 ? 30 : 5)) * (seconds > 300 ? 30 : 5);

/** « 2 min 10 s écoulées » et « ≈ 5 min restantes » d'une génération en cours ; rien si le début n'est pas connu. */
export default function GenerationTiming({ step }: { step: Step }) {
  const unitSeconds = useContext(UnitSecondsContext)(step.name);
  const timing = generationTiming(step, useNow(), unitSeconds);
  if (!timing) return null;
  const { elapsed, remaining } = timing;
  return (
    <span className="timing">
      <span>{durationText(elapsed)} écoulées</span>
      {remaining !== null && <span>{remaining > 0 ? `≈ ${durationText(rounded(remaining))} restantes` : "plus long que prévu"}</span>}
    </span>
  );
}
