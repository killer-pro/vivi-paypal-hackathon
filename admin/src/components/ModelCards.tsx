import { useId } from "react";
import { Link } from "react-router-dom";
import { availableFirst, cardNotice, clipCost, groupOrder, starFills, VIDEO_PROVIDER_LABELS, type Choice, type ModelCard } from "../models";
import { StarIcon } from "./icons";
import "./ModelCards.css";
import { locale, t } from "../i18n";

/** Choix du modèle vidéo en cartes (groupe radio natif, regroupé par provider) : notes, durée ou coût par clip,
 *  carte recommandée ; une carte indisponible ou réservée à l'abonnement est désactivée et dit pourquoi. */
export default function ModelCards({
  cards,
  error,
  value,
  onChange,
  label,
  disabled = false,
}: {
  cards?: ModelCard[];
  error?: string | null;
  /** `null` : aucune carte cochée (choix par défaut pas encore chargé). */
  value: Choice | null;
  onChange: (choice: Choice) => void;
  label: string;
  disabled?: boolean;
}) {
  const name = useId();
  const labelId = useId();
  if (!cards) return <p className={error ? "error" : "muted"}>{error ? t("Modèles indisponibles. {error}", { error }) : t("Chargement des modèles…")}</p>;
  // Groupes qui ont une carte disponible d'abord ; dans chaque groupe, cartes disponibles d'abord.
  const providers = groupOrder(cards);

  return (
    <div className="model-cards" role="radiogroup" aria-labelledby={labelId}>
      <span id={labelId} className="model-cards-label">
        {label}
      </span>
      {providers.map((provider) => (
        <div key={provider} className="model-group">
          <span className="model-group-name">{VIDEO_PROVIDER_LABELS[provider] ?? provider}</span>
          {availableFirst(cards.filter((c) => c.provider === provider)).map((card) => {
              const chosen = card.provider === value?.provider && card.id === value?.model;
              const notice = cardNotice(card);
              return (
                <label
                  key={card.id}
                  className={["model-card", chosen && "is-chosen", (!card.available || card.locked) && "is-unavailable"]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <input
                    type="radio"
                    name={name}
                    checked={chosen}
                    disabled={disabled || !card.available || card.locked}
                    onChange={() => onChange({ provider: card.provider, model: card.id })}
                  />
                  <span className="model-card-body">
                    <span className="model-card-head">
                      <span className="model-card-name">{t(card.name)}</span>
                      {card.recommended && <span className="model-card-badge">{t("recommandé")}</span>}
                      <span className="model-card-cost">{clipCost(card)}</span>
                    </span>
                    <span className="model-card-ratings">
                      <Rating label={t("Vitesse")} value={card.speed} />
                      <Rating label={t("Qualité")} value={card.quality} />
                    </span>
                    {card.description && <span className="model-card-desc">{t(card.description)}</span>}
                    {notice && (
                      <span className={`model-card-reason is-${notice.kind}`}>
                        {notice.text}
                        {notice.kind === "locked" && (
                          <>
                            {" "}
                            <Link to="/plans">{t("Voir les forfaits")}</Link>
                          </>
                        )}
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
        </div>
      ))}
    </div>
  );
}

/** Note en étoiles (lue « 3,5 sur 5 » par un lecteur d'écran), ou « non noté ». */
function Rating({ label, value }: { label: string; value: number | null }) {
  return (
    <span>
      {label}{" "}
      {value === null ? (
        t("non noté")
      ) : (
        <>
          <span className="model-card-stars" aria-hidden>
            {starFills(value).map((fill, i) => (
              <StarIcon key={i} fill={fill} />
            ))}
          </span>
          <span className="sr-only">{t("{value} sur 5", { value: value.toLocaleString(locale) })}</span>
        </>
      )}
    </span>
  );
}
