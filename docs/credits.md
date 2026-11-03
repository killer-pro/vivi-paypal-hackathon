# Crédits

Chaque génération d'un client coûte des crédits : le prix est affiché avant le lancement, les crédits sont réservés au
lancement, réglés à la fin, rendus en cas d'échec. Le compte administrateur n'est jamais limité. Code :
`backend/app/services/credits.py`, `pricing.py`, `services/steps.py` (`preflight_launch`, `launch_step`),
`api/credits_api.py`. Admin : `src/credits.ts`, `pages/Credits.tsx`, `hooks/usePrice.ts`.

## Modèle
- **Solde à deux lots** (`credit_balances`) : crédits d'*abonnement* (consommés en premier) puis *rechargés*. Ce lot ne
  crée aucun crédit d'abonnement (lot 4) ; le modèle, la consommation et le remboursement par lot d'origine sont en place.
- **Registre append-only** (`credit_entries`) : types `signup_grant`, `reserve`, `refund`, `adjust`. Pour chaque lot, la
  somme des entrées redonne toujours le solde (testé après des séquences aléatoires).
- **Réservations** (`credit_reservations`) : `open` puis `closed`, avec le lot d'origine des crédits retenus (`parts`)
  et le prix de chaque scène (`scene_prices`) pour les étapes par scène.
- Jamais de solde négatif (contrainte `CHECK`) ; la réservation verrouille la ligne de solde (`FOR UPDATE`) : deux
  lancements simultanés sur un solde qui n'en paie qu'un, un seul passe, l'autre reçoit `409`.

## Prix
`crédits = coût de revient × marge ÷ valeur du crédit`, arrondi **au crédit supérieur** (calcul `Decimal`).

| Réglage (Réglages, `PUT /api/settings`) | Défaut | Rôle |
|---|---|---|
| `credits_usd_per_credit` | `0.05` | valeur de vente d'un crédit, en dollars |
| `credits_margin` | `2.5` | marge globale |
| `credits_signup_grant` | `100` | crédits offerts à l'inscription |
| `credits_reservation_timeout_min` | `30` | âge à partir duquel une réservation orpheline est balayée |
| `credits_max_parallel_clips` | `1` | générations de clips simultanées par compte |
| `credits_pricing` | JSON | `{"margin_overrides": {}, "flat_usd": {...}, "local_clip_usd": {...}}` |

`flat_usd` (coût de revient par action) : idea 0,01, story 0,03, script 0,05, reference 0,08, voice 0,02 (par scène),
final 0,02, assist 0,005. `local_clip_usd` (clip ComfyUI de 3 s) : fast 0,048, balanced 0,08, precision 0,12, max 0,20 ;
proportionnel à la durée de la scène. `margin_overrides` : marge propre à une action (ou à `clips`). **Ces valeurs sont des
estimations déduites des rapports de la spec (×0,6 / ×1 / ×1,5 / ×2,5, environ 60 crédits pour 30 s en Équilibré) à
calibrer sur des mesures.** Les clips fal.ai sont chiffrés par leur `estimate_cost`, plus l'image de départ Gemini. `music`
et `montage` sont gratuits. Les montants invalides sont refusés en `400`.

## Devis partagé : prix annoncé = prix facturé
`preflight_launch` valide un lancement sans effet de bord (état des étapes, modèle, reprise, devis). `launch_step` et
`POST …/steps/{name}/price` l'appellent tous deux : le prix affiché est exactement le montant réservé. Reprise (`resume`)
et `only_missing` ne chiffrent que les scènes à générer ; une seule scène (`scene_id`), une scène.

## Cycle d'une génération (compte client)
1. **Lancement** : devis, limite de clips simultanés (`409`), `reserve` (`409` « Crédits insuffisants : il vous faut N
   crédits, il vous en reste M »), puis passage atomique à `running`. Si la course sur l'étape est perdue (`StepBusy`) ou si
   la file est indisponible (`503`), la réservation est rendue.
2. **Fin du job** (`run_step`) : `close_for_step`. Étape par scène (clips, voix) : on règle le prix des scènes
   **réellement produites par ce lancement** (réussi ou non), le reste est rendu à son lot d'origine. Autres étapes : prix
   plein si l'étape aboutit, tout rendu sinon.
3. **Fermetures hors fin normale** : annulation (`cancel_step`), timeout et interruption du job, redémarrage du worker
   (`fail_running_steps`), balayeur périodique. Toutes passent par la même fonction `close`, **idempotente** : fermer deux
   fois ne rend qu'une fois.
4. **Balayeur** (`sweep_reservations`, tâche Arq toutes les 10 min) : ferme les réservations ouvertes depuis plus de
   `credits_reservation_timeout_min` dont l'étape ne tourne plus. Une étape encore `running` garde sa réservation : un job de
   clips légitime dure des heures (plafond 24 h), son timeout, l'annulation ou le redémarrage du worker la ferment.
   `max_tries = 1` : un job interrompu n'est jamais rejoué, la fermeture ne dépend donc jamais d'une relance.

## Qui est facturé
Le **propriétaire du projet** (le worker n'a pas d'autre contexte). Un administrateur qui agit sur le projet d'un client
le facture à ce client. Projet de l'admin : aucune réservation. Le budget en dollars par projet (`costs.md`) ne s'applique
qu'aux projets de l'admin ; pour un client, les crédits font office de budget (y compris pour le chat du plan).

## Assistant IA et chat du plan
`POST /ai/assist` (facturé à l'appelant, avec ou sans projet) et `POST /projects/{id}/plan/chat` (facturé au propriétaire
du projet) : `credit_hold` réserve `action_credits("assist")` avant l'appel LLM (`409` sans l'appeler), règle à la sortie
normale, rend tout si l'appel échoue (`502`).

## Crédits d'inscription
`signup_grant` : 100 crédits rechargés, **une seule fois par compte** (index unique partiel en base), uniquement une fois
l'adresse vérifiée, par `/verify` ou `/reset`. Un compte déjà vérifié avant ce lot les reçoit à sa prochaine
vérification ou réinitialisation.

## Interface
Solde dans la barre latérale (« Illimité » pour l'admin), page `/credits` (deux lots et registre paginé), prix sur chaque
bouton de lancement (« Générer les clips · 42 crédits », recalculé quand le modèle change), « Il vous manque N crédits »
sous le bouton quand le solde ne suffit pas (le bouton reste actif : le refus `409` s'affiche tel quel).

## Limites connues
- Une scène produite après une annulation n'est pas facturée (la réservation est déjà fermée).
- Les valeurs initiales de la table de tarifs sont des estimations à calibrer.
- Le bouton « Générer le plan » (autopilot : idée puis histoire) n'affiche pas de prix ; un refus s'affiche si le solde manque.
- Pré-détournement résiduel du lot 1 : un attaquant peut obtenir les 100 crédits d'une adresse qu'il ne possède pas en
  faisant vérifier le compte qu'il a créé.
- Crédits d'abonnement (lot 4, `docs/paiement.md`) : accordés à chaque `invoice.paid`, remis au quota au renouvellement (le
  reliquat expire, entrée `expire`) ; une réservation ouverte au renouvellement rend sa part d'abonnement dans le lot rechargé.
  Nouveaux types de registre : `topup`, `subscription_grant`, `expire`.
