import { Link } from "react-router-dom";
import { serverText } from "../serverText";
import { t } from "../i18n";

/** Motif d'une fonction ou d'une limite du forfait, suivi du lien vers la page des forfaits qui la débloque. */
export default function UpgradeNotice({ reason, className = "muted" }: { reason: string; className?: string }) {
  return (
    <p className={className}>
      {serverText(reason)} <Link to="/plans">{t("Voir les forfaits")}</Link>
    </p>
  );
}
