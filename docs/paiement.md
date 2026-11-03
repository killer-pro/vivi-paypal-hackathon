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
| `billing_config` | JSON : abonnement `{price_id, credits, label}` et recharges `[{id, price_id, credits, label}]` |

Valeurs par défaut de `billing_config` (spec) : abonnement 400 crédits par mois (« 19 $ par mois »), recharges de 200, 500 et
1 200 crédits (« 10 $ », « 24 $ », « 55 $ »). **Les `price_id` sont vides** : une offre sans `price_id` s'affiche « Bientôt
disponible » et ne peut pas s'acheter. Les prix en argent sont définis côté Stripe (produits et prix) ; `label` n'est qu'un
texte affiché. Une valeur invalide est refusée en `400`.

Mise en route : créer dans Stripe un produit d'abonnement mensuel et un prix unique par recharge, saisir leurs `price_id`,
ajouter le point d'accès `POST {API}/api/stripe/webhook` avec les événements `checkout.session.completed`, `invoice.paid` et
`customer.subscription.deleted`, copier son secret dans `stripe_webhook_secret`. En local : `stripe listen --forward-to
localhost:8000/api/stripe/webhook`. Activer le portail client dans le tableau de bord Stripe (annulation autorisée).

## Parcours d'achat
1. `GET /api/billing` : offre, état d'abonnement, `manageable` (le compte a un client Stripe).
2. `POST /api/billing/checkout {kind: "subscription" | "topup", pack_id?}` → `{url}` de la page de paiement. Le client Stripe
   du compte est créé au premier achat (`users.stripe_customer_id`). Refus : `403` adresse non vérifiée, `404` recharge
   inconnue, `409` offre sans prix Stripe ou compte déjà abonné (aller au portail), `502` refus de Stripe (message affiché).
   Retour : `/credits?checkout=success|cancelled`.
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
- Un paiement payé après le retour sur `/credits` peut demander quelques secondes : l'écran relit le solde trois fois.

## PayPal (recharges)
Second moyen de paiement des **recharges** (pas encore l'abonnement), pour les comptes sans carte acceptée par Stripe. Code :
`backend/app/services/paypal_client.py` (Orders v2 par `httpx`, jeton OAuth mis en cache, `FakePayPal` pour les tests),
`api/billing_api.py` (`/billing/paypal/order`, `/billing/paypal/capture`), `api/paypal_webhook.py`, `services/payments.py`
(`apply_paypal_capture`, `record_event` partagé avec Stripe) ; admin : `BillingOffers.tsx`, `billing.ts`.

Réglages : `paypal_client_id`, `paypal_client_secret` (chiffré), `paypal_webhook_id`, `paypal_mode` (`sandbox` par défaut, ou `live`).
Chaque pack de `billing_config` a un `paypal_amount` (dollars à deux décimales, « 10.00 ») ; vide : pas d'achat PayPal.

Parcours : `POST /api/billing/paypal/order {pack_id}` crée la commande (`custom_id` = `<compte>:<pack>`) et renvoie l'URL
d'approbation ; PayPal renvoie sur `/credits?paypal=success&token=<commande>` ; l'écran appelle `POST /api/billing/paypal/capture`,
qui capture et crédite. Le webhook `PAYMENT.CAPTURE.COMPLETED` (signature vérifiée par l'API PayPal) est le filet : même
identifiant de capture (`paypal:<id>` dans `stripe_events`), donc jamais de double crédit. Une capture n'est créditée que si
son statut est `COMPLETED`, son montant celui du pack (USD) et son compte celui du `custom_id` ; `403` si la commande est celle d'un autre compte. Une capture déjà faite (PayPal : `ORDER_ALREADY_CAPTURED`) répond `{"credited": 0}` et non une erreur ; l'identifiant de commande est validé (`[A-Za-z0-9_-]{1,64}`) avant d'entrer dans l'URL appelée avec nos identifiants. L'écran ne capture qu'une fois par commande.
