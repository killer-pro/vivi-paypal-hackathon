# Admin SaaS

Écrans et routes réservés à l'administrateur (`403` pour un autre compte) : clients, ajustement de crédits, tarifs et
marges. Code : `backend/app/api/admin_api.py`, `services/margins.py`, `services/credits.py` (`adjust`) ; admin :
`pages/Customers.tsx`, `CustomerDetail.tsx`, `Pricing.tsx`, logique pure dans `adminSaas.ts`.

## Clients (`/clients`)
- `GET /api/admin/customers?q=&limit=&offset=` : comptes du plus récent au plus ancien, avec offre (`subscribed`,
  `subscription_ends_at`), solde par lot et **crédits consommés** (`spent` : somme des `used` des réservations fermées).
  `q` filtre sur l'adresse e-mail (sans tenir compte de la casse).
- `GET /api/admin/customers/{id}` : le compte et son registre de crédits, paginé comme `GET /api/credits`
  (`next_before_id`). `404` si le compte n'existe pas.

## Ajustement manuel
`POST /api/admin/customers/{id}/credits {amount, bucket, reason}` (`bucket` : `subscription` ou `topup`).
- `amount` entier signé, jamais nul ; `reason` obligatoire (300 caractères max) et conservé dans le registre
  (`kind = adjust`), avec le même verrou de solde que les réservations.
- Un retrait ne peut pas faire passer un lot sous zéro : `409`, rien n'est écrit. Le compte administrateur, illimité,
  ne s'ajuste pas (`409`).
- Réponse : le nouveau solde.

## Tarifs (`/pricing`)
Le formulaire écrit les réglages `credits_usd_per_credit`, `credits_margin`, `credits_signup_grant` et la table
`credits_pricing` (exceptions de marge, coûts forfaitaires, coût d'un clip local par profil) par `PUT /api/settings`,
donc avec la validation de `docs/credits.md`. Les prix s'appliquent aux lancements suivants. Un champ d'exception vidé est
retiré de la table.

## Marges (`GET /api/admin/margins?since=`)
Pour chaque action : coût de revient (`provider_calls` des projets de clients), crédits facturés (réservations fermées,
`used`), revenu estimé (crédits × valeur nominale du crédit) et marge observée (`ratio` = revenu ÷ coût, `null` sans
coût). Les appels de l'assistant (`assist:*`) sont regroupés sous `assist`. Les projets de l'administrateur, non
facturés, sont exclus. L'écran signale en couleur les marges sous la marge visée.

## Limites connues
- Pas de ventilation par profil de génération : le profil n'est pas enregistré avec l'appel ni la réservation, le
  tableau est par action.
- Le revenu est estimé au prix nominal du crédit (0,05 $), pas aux paiements réellement encaissés (les packs sont
  dégressifs, le crédit d'inscription est gratuit).
- Pas de suppression de compte ni de changement d'offre depuis l'écran ; l'abonnement se pilote par Stripe
  (`docs/paiement.md`) ou `scripts/set_subscription.py`.
