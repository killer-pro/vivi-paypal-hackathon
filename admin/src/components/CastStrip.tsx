import type { CastMember, CastStatus } from "../casting";
import type { Flow } from "../hooks/useProject";
import { ELEMENT_KINDS } from "../story";
import { RefreshIcon, WandIcon } from "./icons";
import "./Cast.css";
import { t, tn } from "../i18n";

/** Libellé et classe de statut (`.st-*`) des états à signaler ; une image prête se passe de badge. */
const BADGES: Partial<Record<CastStatus, { label: string; st: string }>> = {
  generating: { label: t("Génération…"), st: "st-running" },
  failed: { label: t("Échec"), st: "st-failed" },
  missing: { label: t("À générer"), st: "st-pending" },
};

/** Classe de statut (`.st-*`) d'un élément : teinte son cadre vide (qui pulse pendant la génération) et son badge. */
const statusClass = (status: CastStatus) => BADGES[status]?.st ?? "";

/** Vignette 9:16 d'un élément : son image, sinon un cadre vide (pointillés) ; sans élément, « Sans image ». Le cadre vide
 *  dit son état en toutes lettres (infobulle et lecteur d'écran), la teinte n'en est qu'un renfort. */
export function CastFrame({ member }: { member?: CastMember }) {
  if (member?.imageUrl) return <img className="frame-9x16" src={member.imageUrl} alt={member.name} />;
  const none = !member || member.status === "none";
  const label = [member?.name, none ? t("Sans image") : BADGES[member.status]?.label].filter(Boolean).join(" : ");
  return (
    <div className={`frame-9x16 cast-empty ${member ? statusClass(member.status) : ""}`} role="img" aria-label={label} title={label}>
      {none && t("Sans image")}
    </div>
  );
}

/** Bandeau du casting (écran Plan, onglets Script et Clips) : une vignette 9:16 par élément récurrent, avec son état et
 *  l'action qui le débloque (génération de l'image de ce seul élément). */
export default function CastStrip({ cast, flow }: { cast: CastMember[]; flow: Pick<Flow, "run" | "busy"> }) {
  if (!cast.length) return null;
  const generate = (id: string) => flow.run("reference", undefined, { overrides: { reference_id: id } });
  return (
    <ul className="cast-strip" aria-label={t("Casting")}>
      {cast.map((m) => {
        const badge = BADGES[m.status];
        return (
          <li key={m.id} className={`cast-member ${statusClass(m.status)}`} data-status={m.status}>
            <CastFrame member={m} />
            {badge && <span className="status-badge cast-badge">{badge.label}</span>}
            <div className="cast-meta">
              <strong>{m.name}</strong>
              <span className="muted">
                {ELEMENT_KINDS[m.kind]}, {tn(m.scenes.length, "{n} scène", "{n} scènes")}
              </span>
            </div>
            {m.status === "failed" && (
              <button type="button" className="btn btn-small" disabled={flow.busy} onClick={() => generate(m.id)}>
                <RefreshIcon />
                {t("Réessayer")}
              </button>
            )}
            {m.status === "missing" && (
              <button type="button" className="btn btn-small" disabled={flow.busy} onClick={() => generate(m.id)}>
                <WandIcon />
                {t("Générer")}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
