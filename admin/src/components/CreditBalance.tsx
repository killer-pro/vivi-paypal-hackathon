import { NavLink } from "react-router-dom";
import { useCredits } from "../hooks/useCredits";
import { CoinIcon } from "./icons";

/** Entrée « Crédits » de la barre latérale, avec le solde (« Illimité » pour l'administrateur). */
export default function CreditBalance() {
  const { data } = useCredits();
  return (
    <NavLink to="/credits" className="nav-link" title="Solde et historique des crédits">
      <CoinIcon />
      <span>Crédits</span>
      {data && <span className="credit-chip">{data.unlimited ? "Illimité" : data.balance.total}</span>}
    </NavLink>
  );
}
