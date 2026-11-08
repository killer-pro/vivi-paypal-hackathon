import { NavLink } from "react-router-dom";
import { useCredits } from "../hooks/useCredits";
import { CoinIcon } from "./icons";
import { t } from "../i18n";

/** Entrée « Crédits » de la barre latérale, avec le solde (« Illimité » pour l'administrateur). */
export default function CreditBalance() {
  const { data } = useCredits();
  return (
    <NavLink to="/credits" className="nav-link" title={t("Solde et historique des crédits")}>
      <CoinIcon />
      <span>{t("Crédits")}</span>
      {data && <span className="credit-chip">{data.unlimited ? t("Illimité") : data.balance.total}</span>}
    </NavLink>
  );
}
