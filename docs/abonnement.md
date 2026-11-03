# Accès par abonnement

Certaines fonctions sont réservées aux comptes abonnés. Un **point d'accroche unique** (`backend/app/services/access.py`)
décide, et renvoie sinon un motif lisible (« Réservé à l'abonnement : le profil Précision ») que l'interface affiche au
lieu de masquer le contrôle. Le paiement et le renouvellement (Stripe) arrivent au lot 4 ; ce lot lit l'état d'abonnement.

## État d'abonnement
`users.subscription_ends_at` (migration `0017`). Un compte est **abonné** tant que cette date est dans le futur, et le
compte administrateur l'est toujours (`User.is_subscribed`). Une annulation ne prolonge pas la date : les fonctions
restent donc ouvertes jusqu'à la fin de la période payée, puis se verrouillent. Perdre l'abonnement ne supprime rien
(projets, clips, crédits rechargés).

Le paiement (`docs/paiement.md`) l'écrit sur `invoice.paid` et la termine sur `customer.subscription.deleted`. Pour des essais sans Stripe, la date se fixe avec `backend/scripts/set_subscription.py --email … --until AAAA-MM-JJ` (ou `--off`), sans
redémarrage.

## Fonctions réservées (réglage `subscription_locked`)
Réglage JSON éditable par l'admin (`PUT /api/settings`, valeur invalide refusée en `400`) :
`{"profiles": ["precision", "max"], "reference": true, "styles": ["realistic", "anime", "illustration"]}`.
- `profiles` : profils de génération ComfyUI réservés (Précision et Maximum par défaut ; l'ancien nom `workflow` vaut `max`) ;
- `reference` : génération et import d'images de référence ;
- `styles` : styles visuels réservés (choisir « Aucun » reste libre).
Une fonction absente de la liste est libre : la liste est de la configuration, pas du code d'écran.

## Où c'est appliqué
- **Lancement d'une étape** (`preflight_launch`, donc aussi l'endpoint de prix) : profil de l'étape clips (choix ponctuel,
  paramètres enregistrés ou réglage par défaut), étape `reference`. `403` avant tout le reste, avant la réservation de crédits.
- **Autopilot** : un compte non abonné saute l'étape `reference` (validée sans résultat, comme sans éléments récurrents) ; un
  profil réservé fait échouer l'étape avec le motif.
- `POST /projects/{id}/reference/upload` (import d'image de référence) ; création et modification du style d'un projet.
- Le compte concerné est le **propriétaire du projet** pour les générations et les imports (un administrateur qui aide sur
  un projet ne débloque rien), et l'appelant pour la création d'un projet.

## API
- `403 {"detail": "Réservé à l'abonnement : …"}` sur les refus ci-dessus (`SubscriptionRequired`).
- `GET /api/access` : `{subscribed, subscription_ends_at, locked: {profiles, reference, styles}, reasons: {reference, style}}`
  (`locked` est vide pour un abonné).
- `GET /api/providers/models` : chaque carte vidéo porte `locked` et `locked_reason`, distincts de `available` (état
  technique du modèle). `GET /api/auth/me` expose `subscribed` et `subscription_ends_at`.

## Interface
Les cartes de profil réservées restent visibles, grisées, avec leur motif ; les styles réservés sont des pastilles
désactivées (motif en infobulle) ; les contrôles de l'image de référence sont désactivés avec le motif sous eux. Code :
`admin/src/access.ts`, `models.ts` (`locked`), `components/ModelCards.tsx`, `Pills.tsx`, `panels/ReferenceSection.tsx`.

## Limites connues
- L'achat et la gestion passent par Stripe (`docs/paiement.md`) ; l'ajustement manuel d'un abonnement par l'admin viendra au lot 5.
- Un projet créé avec un style puis dont le propriétaire perd l'abonnement garde son style (seule la modification est refusée).
