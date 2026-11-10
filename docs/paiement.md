# Paiement (Stripe)

Abonnement mensuel et recharges de crédits par Stripe Checkout ; gestion des achats dans le portail client Stripe. Les
crédits et l'état d'abonnement ne changent que sur **webhook signé**, de façon **idempotente**. Code :
`backend/app/services/stripe_client.py`, `billing.py`, `payments.py`, `api/billing_api.py`, `api/stripe_webhook.py` ;
admin : `src/billing.ts`, `components/BillingOffers.tsx` (page Crédits).

## Configuration (Réglages, ou `PUT /api/settings`)
| Réglage | Rôle |
|---|---|
| `stripe_secret_key` | clé secrète de l'API Stripe (chiffrée en base, masquée) |
| `stripe_webhook_secret` | secret de signature du point d'accès webhook (`whsec_…`, chiffré) ; vide : tous les webhooks sont refusés |
| `billing_config` | JSON : forfaits `tiers` (crédits, prix, avantages ; `docs/abonnement.md`), niveau `free` et recharges `packs` `[{id, price_id, credits, label, paypal_amount}]` |

Valeurs par défaut de `billing_config` : forfaits Starter, Créateur et Pro (`docs/abonnement.md`), recharges de 200, 500 et
1 200 crédits (« 10 $ », « 24 $ », « 55 $ »). **Les `price_id` sont vides** : une offre sans `price_id` ne peut pas
s'acheter par Stripe. Les prix en argent sont définis côté Stripe (produits et prix) ; `label` n'est qu'un
texte affiché. Une valeur invalide est refusée en `400`.

Mise en route : créer dans Stripe un produit d'abonnement mensuel et un prix unique par recharge, saisir leurs `price_id`,
ajouter le point d'accès `POST {API}/api/stripe/webhook` avec les événements `checkout.session.completed`, `invoice.paid` et
`customer.subscription.deleted`, copier son secret dans `stripe_webhook_secret`. En local : `stripe listen --forward-to
localhost:8000/api/stripe/webhook`. Activer le portail client dans le tableau de bord Stripe (annulation autorisée).

## Parcours d'achat
1. `GET /api/billing` : offre, état d'abonnement, `manageable` (le compte a un client Stripe).
2. `POST /api/billing/checkout {kind: "subscription" | "topup", tier_id?, pack_id?}` → `{url}` de la page de paiement
   (`tier_id` : forfait, exigé pour un abonnement, recopié dans les métadonnées de l'abonnement Stripe pour que `invoice.paid`
   retrouve le forfait ; à défaut, le premier). Le client Stripe
   du compte est créé au premier achat (`users.stripe_customer_id`). Refus : `404` recharge
   ou forfait inconnu, `422` forfait manquant, `409` offre sans prix Stripe ou compte déjà abonné (aller au portail), `502` refus de Stripe (message affiché).
   Retour : `/plans?checkout=success|cancelled`.
3. `POST /api/billing/portal` → `{url}` du portail du **compte connecté** seulement (`409` sans achat).

Rien n'est crédité par ces appels.

## Webhook (`POST /api/stripe/webhook`)
Ouvert (pas de session), protégé par `Stripe-Signature` (HMAC-SHA256 de `t.payload`, tolérance 5 minutes, comparaison à temps
constant) : `400` si la signature est absente, fausse ou périmée. L'enregistrement de l'événement (`stripe_events`) et ses
effets partagent **une transaction** : un événement déjà traité est acquitté sans effet (`duplicate: true`), un échec ne le
marque pas et Stripe rejoue. Un événement pour un compte inconnu ou un type non géré est acquitté (`200`) et journalisé.
- `checkout.session.completed` (mode `payment`, payé) : `credits` de la recharge ajoutés au lot rechargé (entrée `topup`).
- `invoice.paid` (facture d'abonnement) : fin de période enregistrée (jamais raccourcie par une facture plus ancienne) et
  **lot d'abonnement remis au quota** : le reliquat expire (`expire`), le quota est accordé (`subscription_grant`). Les
  réservations ouvertes au renouvellement voient leur part d'abonnement passer sur le lot rechargé : réglées ou rendues
  là, jamais de solde négatif.
- `customer.subscription.deleted` : accès terminé, lot d'abonnement expiré ; les crédits rechargés restent acquis.
Une annulation en cours de période n'envoie pas `deleted` : l'accès et les crédits courent jusqu'à la fin de la période payée.

## Tests et développement
`FAKE_PROVIDERS=true` et les tests utilisent `FakeStripe` (aucun appel réseau). Les tests de webhook signent leurs propres
événements. Le client réel est testé avec un transport `httpx` simulé (formulaire, en-tête `Authorization`).

## Limites connues
- Pas de remboursement ni de litige : un remboursement Stripe ne retire pas les crédits (à traiter à la main, ajustement lot 5).
- Pas de changement d'offre (un seul abonnement) ; la TVA et la facturation sont celles de Stripe.
- Un paiement payé après le retour sur `/plans` peut demander quelques secondes : l'écran relit le solde trois fois.

## PayPal (recharges et abonnement)
Second moyen de paiement des **recharges** et des **forfaits**, pour les comptes sans carte acceptée par Stripe. Code :
`backend/app/services/paypal_client.py` (Orders v2 par `httpx`, jeton OAuth mis en cache, `FakePayPal` pour les tests),
`api/billing_api.py` (`/billing/paypal/order`, `/billing/paypal/capture`, `/billing/paypal/subscription[/confirm|/cancel]`),
`api/paypal_webhook.py`, `services/payments.py` (`apply_paypal_capture`, `apply_paypal_subscription`, `handle_paypal_event`,
`record_event` partagé avec Stripe) ; admin : `BillingOffers.tsx`, `billing.ts`.

Réglages : `paypal_client_id`, `paypal_client_secret` (chiffré), `paypal_webhook_id`, `paypal_mode` (`sandbox` par défaut, ou `live`).
Chaque pack de `billing_config` a un `paypal_amount` (dollars à deux décimales, « 10.00 ») ; vide : pas d'achat PayPal.

Parcours : `POST /api/billing/paypal/order {pack_id}` crée la commande (`custom_id` = `<compte>:<pack>`) et renvoie l'URL
d'approbation ; PayPal renvoie sur `/plans?paypal=success&token=<commande>` ; l'écran appelle `POST /api/billing/paypal/capture`,
qui capture et crédite. Le webhook `PAYMENT.CAPTURE.COMPLETED` (signature vérifiée par l'API PayPal) est le filet : même
identifiant de capture (`paypal:<id>` dans `stripe_events`), donc jamais de double crédit. Une capture n'est créditée que si
son statut est `COMPLETED`, son montant celui du pack (USD) et son compte celui du `custom_id` ; `403` si la commande est celle d'un autre compte. Une capture déjà faite (PayPal : `ORDER_ALREADY_CAPTURED`) répond `{"credited": 0}` et non une erreur ; l'identifiant de commande est validé (`[A-Za-z0-9_-]{1,64}`) avant d'entrer dans l'URL appelée avec nos identifiants. L'écran ne capture qu'une fois par commande.

### Abonnement mensuel par PayPal (Subscriptions)
Un plan PayPal (« P-… ») **par forfait**, créé une fois par mode (`sandbox` / `live`) : `cd backend && .venv/bin/python
scripts/paypal_create_plan.py --tier starter` (puis `creator`, `pro`) crée le produit et le plan mensuel au `paypal_amount` du forfait
et inscrit `paypal_plan_id` dans ce forfait de `billing_config` (vide : pas d'abonnement PayPal à ce forfait). `users.paypal_subscription_id` (migration `0019`) garde l'abonnement en cours du compte.

Parcours : `POST /api/billing/paypal/subscription {tier_id}` crée l'abonnement au plan du forfait (`custom_id` = identifiant du compte) et
renvoie l'URL d'approbation (`404` forfait inconnu, `409` forfait sans plan PayPal ou compte déjà abonné,
`502` refus de PayPal) ; PayPal renvoie sur
`/plans?paypal_sub=success&subscription_id=…` ; l'écran appelle `POST /api/billing/paypal/subscription/confirm`, qui **relit l'abonnement chez
PayPal** (jamais le corps d'un événement), vérifie qu'il est au compte connecté (`403` sinon) et, si au moins un mois est prélevé
(`cycle_executions` REGULAR), retrouve le forfait par le plan PayPal de l'abonnement (plan qui n'est plus dans l'offre : forfait actuel du compte,
ou le premier, si l'abonnement est celui du compte, ce qui couvre les abonnés de l'ancien plan unique ; sinon ignoré,
journalisé), fixe `users.plan_id`, accorde le quota du
forfait (`credits`, remise à zéro du lot d'abonnement) et fixe `subscription_ends_at` à la prochaine
échéance (`next_billing_time`, sans jamais raccourcir). Réponse : `{activated, credited}`.

Idempotence : un cycle payé = un événement `paypal:sub:<abonnement>:<mois payés>` dans `stripe_events`. La confirmation de l'écran et les
webhooks `PAYMENT.SALE.COMPLETED` (renouvellement mensuel), `BILLING.SUBSCRIPTION.ACTIVATED`, `…CANCELLED` et `…EXPIRED` appellent le même
code : un mois n'est jamais crédité deux fois, et le webhook active un client qui a fermé l'onglet. **Changement de forfait** : un abonné peut créer un abonnement à un autre forfait (le même forfait encore renouvelé : 409).
L'abonnement en cours n'est touché qu'au premier mois payé du nouveau (confirmation ou webhook) : le nouveau devient
`paypal_subscription_id`, l'ancien est annulé chez PayPal (en cas d'échec, erreur au journal : à annuler à la main), le
quota d'abonnement est remis à celui du nouveau forfait et la période payée la plus longue est gardée. Un changement
abandonné chez PayPal ne change rien. **Annulation** (`POST /api/billing/paypal/subscription/cancel`, ou événement) : plus de renouvellement, la période déjà payée reste
acquise (`subscription_ends_at` et `plan_id` inchangés : les avantages courent jusqu'à la fin de la période, puis le compte
repasse au niveau Gratuit) et l'abonnement est libéré. Limite connue : le reliquat de crédits d'abonnement d'un compte annulé n'expire
qu'à une remise à zéro (pas de balayage à l'échéance). `GET /api/billing` expose, par forfait, `paypal_purchasable` (plan ET identifiants), le forfait courant
(`current_tier`) et `paypal_cancellable` ; `FakePayPal` simule l'abonnement (`approve_subscription`) pour les tests et `FAKE_PROVIDERS=true`.

Événements à cocher dans le webhook PayPal : `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.SALE.COMPLETED`, `BILLING.SUBSCRIPTION.ACTIVATED`,
`BILLING.SUBSCRIPTION.CANCELLED`, `BILLING.SUBSCRIPTION.EXPIRED`.

**Brancher le webhook (essayé en bac à sable).** PayPal doit joindre l'API : `cloudflared tunnel --url http://localhost:8000` donne une
adresse `https://….trycloudflare.com` (elle change à chaque lancement). Créer le webhook sur cette adresse + `/api/paypal/webhook`
pour l'événement `PAYMENT.CAPTURE.COMPLETED` (tableau de bord développeur, ou `POST /v1/notifications/webhooks`), puis saisir son
identifiant dans Réglages (`paypal_webhook_id`). Essai : commande approuvée, capture de l'écran bloquée, capture faite côté serveur ;
PayPal a livré l'événement signé en moins d'une minute et les 200 crédits sont arrivés une seule fois.
