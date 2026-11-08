# Forfaits et accès

Vivi se vend en **forfaits mensuels** (Starter, Créateur, Pro) ; un compte sans abonnement est au niveau **Gratuit** (crédits
d'inscription et packs, sans les avantages). Un **point d'accroche unique** (`backend/app/services/access.py`) calcule les
avantages d'un compte et renvoie, quand il refuse, un motif lisible qui nomme le forfait qui débloque la fonction
(« Réservé au forfait Créateur : le profil Maximum »). L'interface affiche ce motif au lieu de masquer le contrôle.

## Forfaits (réglage `billing_config`)
Réglage JSON éditable par l'admin (`PUT /api/settings`, valeur invalide refusée en `400`), décrit dans
`services/billing.py` (`Tier`, `Perks`, `Pack`) :
`{"tiers": [{id, name, label, credits, price_id, paypal_amount, paypal_plan_id, perks}], "free": {perks}, "packs": [...]}`.
Les avantages (`perks`) : `queue_max` (demandes en file par projet), `references_max` (images de référence par projet),
`profiles` (profils de génération), `max_duration_s` (durée max d'une vidéo), `parallel_clips` (clips générés en même
temps), `styles` (styles visuels ; « Aucun » reste libre).

| | Gratuit | Starter | Créateur | Pro |
|---|---|---|---|---|
| Prix (PayPal) | — | 9 $ / mois | 19 $ / mois | 49 $ / mois |
| Crédits mensuels | 0 | 1 200 | 3 000 | 9 000 |
| Demandes en file | 1 | 2 | 4 | 8 |
| Images de référence | 2 | 4 | 8 | 16 |
| Profils | Rapide, Équilibré | + Précision | tous | tous |
| Durée max | 30 s | 60 s | 90 s | 180 s |
| Clips en parallèle | 1 | 1 | 2 | 3 |
| Styles visuels | non | oui | oui | oui |

Un réglage enregistré dans l'ancien format (abonnement unique, clé `subscription`) ou mal formé n'est pas lu : les
forfaits par défaut s'appliquent (`load_billing`), rien ne plante.

## Forfait d'un compte
`users.plan_id` (migration `0020`) et `users.subscription_ends_at` (migration `0017`). Un compte est **abonné** tant que
la date de fin est dans le futur (`User.is_subscribed`) ; son forfait est alors `plan_id`, ou le **premier forfait**
(Starter) si `plan_id` est absent ou inconnu (abonnés d'avant les forfaits). Abonnement terminé : niveau Gratuit. Le compte
administrateur n'est jamais limité (`billing.UNLIMITED`). Perdre l'abonnement ne supprime rien (projets, clips, crédits
rechargés).

Le paiement (`docs/paiement.md`) écrit la date et le forfait. Pour des essais, `backend/scripts/set_subscription.py
--email … --until AAAA-MM-JJ [--plan starter|creator|pro]` (ou `--off`), sans redémarrage.

## Motifs de refus
- Fonction (profil, style) : « Réservé au forfait {premier forfait qui la débloque} : {fonction} », ou « Indisponible :
  {fonction} » si aucun forfait ne la débloque (`access.reason`, `access.require`).
- Limite : « Limite de votre forfait : 30 s (forfait Starter : 60 s) », la parenthèse nommant le premier forfait qui
  suffit, omise s'il n'y en a pas (`access.limit_reason`, `access.require_limit`).
- Les deux sont des `403 {"detail": motif}` (`SubscriptionRequired`).

## Où c'est appliqué
- **Lancement d'une étape** (`preflight_launch`, donc aussi l'endpoint de prix) : profil de l'étape clips (choix ponctuel,
  paramètres enregistrés ou réglage par défaut). `403` avant la réservation de crédits ; en autopilot, l'étape échoue avec
  le motif.
- Création et modification du style et de la **durée** d'un projet (`target_duration_s` au-delà de `max_duration_s` : `403`),
  et lancement des clips et de la voix si la somme des scènes dépasse `max_duration_s` de plus de 20 % (écart toléré d'un
  script généré ; le chat du plan ou un script modifié ne contournent donc pas la limite).
- Identifiant de forfait : minuscules, chiffres, `_` et `-`, 20 caractères au plus (`users.plan_id`).
- **Images de référence** (ouvertes à tous, limitées en nombre d'**éléments** distincts : clé `meta.ref` des assets
  `reference`, l'image du projet sans élément compte pour un) : un import qui ajoute un élément au-delà de
  `references_max` est refusé, remplacer l'image d'un élément existant reste permis ; lancer l'étape `reference` avec
  plus d'éléments que la limite est refusé. L'**autopilot** et le lancement automatique après le script génèrent
  seulement les `references_max` premiers éléments (`reference_ids`) au lieu d'échouer.
- **File d'attente** par projet (`queue_max`, `docs/file-attente.md`) et **clips en parallèle** par compte
  (`parallel_clips`, `docs/credits.md`).
- Le compte concerné est le **propriétaire du projet** pour les générations (un administrateur qui aide sur un projet ne
  débloque rien), et l'appelant pour la création d'un projet.

## API
- `GET /api/access` : `{subscribed, subscription_ends_at, tier: {id, name} | null, perks: {...}, locked: {profiles,
  styles}, reasons: {style}}`.
- `GET /api/providers/models` : chaque carte vidéo porte `locked` et `locked_reason`, distincts de `available` (état
  technique du modèle). `GET /api/auth/me` expose `subscribed` et `subscription_ends_at`.

## Interface
- **Page Forfaits** (`/plans`, entrée « Forfaits » de la navigation pour tout compte ; `pages/Plans.tsx`,
  `components/BillingOffers.tsx`, logique `plans.ts`) : trois cartes côte à côte (nom, prix, crédits mensuels, bande de
  cadres 9:16 « ≈ N vidéos de 30 s », avantages cochés, bouton « S'abonner avec PayPal » ou « Forfait actuel » /
  « Annuler mon abonnement PayPal »), rappel du niveau « Sans abonnement », puis les recharges (« avantages du niveau
  gratuit »). Les retours de PayPal et Stripe arrivent sur `/plans`. L'écran Crédits renvoie vers cette page.
- Fonctions verrouillées visibles, grisées, avec leur motif suivi de « Voir les forfaits » (`UpgradeNotice`) : cartes de
  profil, images de référence au-delà de la limite (`access.ts::referenceLimit`, remplacer une image reste permis),
  durées de la nouvelle vidéo au-delà du forfait (pastilles désactivées), styles (pastilles désactivées, motif en
  infobulle). La file d'attente du Studio suit `perks.queue_max` (`access.ts::queueMax`).
- Les motifs serveur sont traduits par `admin/src/serverText.ts`.

## Limites connues
- Pas de changement de forfait en cours de période : on annule, puis on s'abonne au nouveau à la fin de la période.
- Un projet créé avec un style puis dont le propriétaire perd l'abonnement garde son style (seule la modification est refusée).
