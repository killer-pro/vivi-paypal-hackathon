import { formatCredits, quoteShortfall, type PriceQuote } from "../credits";

/** Sous un bouton de lancement : le manque quand le solde ne couvre pas le prix. Le bouton reste actif, c'est le
 *  lancement qui refuse (409) avec le détail du solde. */
export default function PriceNote({ quote }: { quote: PriceQuote | null }) {
  const missing = quote ? quoteShortfall(quote) : 0;
  if (missing === 0) return null;
  return (
    <p className="price-note" role="status">
      Il vous manque {formatCredits(missing)}
    </p>
  );
}
