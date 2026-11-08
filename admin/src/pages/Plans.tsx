import BillingOffers from "../components/BillingOffers";
import { notifyCreditsChanged } from "../hooks/useCredits";
import { t } from "../i18n";

/** Forfaits mensuels côte à côte, rappel du niveau gratuit, puis les recharges ; retours de paiement PayPal et Stripe. */
export default function Plans() {
  return (
    <div className="plans-page">
      <header className="page-head">
        <h1>{t("Forfaits")}</h1>
      </header>
      <BillingOffers onPaid={notifyCreditsChanged} />
    </div>
  );
}
