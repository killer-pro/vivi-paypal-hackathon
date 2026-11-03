import { useId } from "react";
import { cardNotice, clipCost, starFills, VIDEO_PROVIDER_LABELS, type Choice, type ModelCard } from "../models";
import { StarIcon } from "./icons";
import "./ModelCards.css";

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
  if (!cards) return <p className={error ? "error" : "muted"}>{error ? `Modèles indisponibles. ${error}` : "Chargement des modèles…"}</p>;
  // Le groupe de la carte recommandée en premier, les autres dans l'ordre de l'API.
  const first = cards.find((c) => c.recommended)?.provider;
  const providers = [...new Set(cards.map((c) => c.provider))].sort((a, b) => Number(b === first) - Number(a === first));

  return (
    <div className="model-cards" role="radiogroup" aria-labelledby={labelId}>
      <span id={labelId} className="model-cards-label">
        {label}
      </span>
      {providers.map((provider) => (
        <div key={provider} className="model-group">
          <span className="model-group-name">{VIDEO_PROVIDER_LABELS[provider] ?? provider}</span>
          {cards
            .filter((c) => c.provider === provider)
            .map((card) => {
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
                      <span className="model-card-name">{card.name}</span>
                      {card.recommended && <span className="model-card-badge">recommandé</span>}
                      <span className="model-card-cost">{clipCost(card)}</span>
                    </span>
                    <span className="model-card-ratings">
                      <Rating label="Vitesse" value={card.speed} />
                      <Rating label="Qualité" value={card.quality} />
                    </span>
                    {card.description && <span className="model-card-desc">{card.description}</span>}
                    {notice && <span className={`model-card-reason is-${notice.kind}`}>{notice.text}</span>}
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
        "non noté"
      ) : (
        <>
          <span className="model-card-stars" aria-hidden>
            {starFills(value).map((fill, i) => (
              <StarIcon key={i} fill={fill} />
            ))}
          </span>
          <span className="sr-only">{`${String(value).replace(".", ",")} sur 5`}</span>
        </>
      )}
    </span>
  );
}
