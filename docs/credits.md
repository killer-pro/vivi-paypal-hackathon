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
| `credits_usd_per_credit` | `0.01` | valeur d'un crédit, en dollars (base du calcul) |
| `credits_margin` | `3` | marge globale : tout est vendu à environ 3 fois le coût réel |
| `credits_signup_grant` | `200` | crédits offerts à l'inscription (de quoi faire une vidéo de 30 s en Rapide) ; surchargeable par `CREDITS_SIGNUP_GRANT` dans `backend/.env` |
| `credits_reservation_timeout_min` | `30` | âge à partir duquel une réservation orpheline est balayée |
| `credits_pricing` | JSON | `{"margin_overrides": {}, "flat_usd": {...}, "local_clip_usd": {...}}` |

`flat_usd` (coût de revient par action, mesuré dans `provider_calls` le 2026-11-07 sur les fournisseurs du serveur) :
idea 0,002, story 0,006, script 0,005 (Groq / Gemini), reference 0,04 (Flux dev sur Comfy Cloud), voice 0,012 par scène
(ElevenLabs, ≈ 0,011 $ mesuré), final 0,002, assist 0,003. `local_clip_usd` (clip ComfyUI local de 3 s) : fast 0,048,
balanced 0,08, precision 0,12, max 0,20 ; proportionnel à la durée de la scène. `margin_overrides` : marge propre à une
action (ou à `clips`).

Les clips **Comfy Cloud** sont chiffrés par leur coût cloud (`providers/comfycloud.py::cloud_clip_usd`) : secondes de GPU
mesurées par profil pour 3 s (`GPU_S_PER_CLIP` : fast 22, balanced 26, precision 45, max 60), proportionnelles à la durée,
au tarif de Comfy Cloud. L'image de départ Kontext s'exécute dans le même graphe que le clip : son coût y est compris, sans
ajout par scène (Rapide avec référence ≈ 0,021 $, soit 7 crédits). Les clips fal.ai sont chiffrés par leur `estimate_cost` ;
l'image de départ Gemini s'ajoute par scène. En mode factice (`FAKE_PROVIDERS=true`), les clips Comfy Cloud gardent ce coût.

**Vidéo de 30 s** (`pricing.video_credits` : 10 scènes de 3 s, clips Comfy Cloud) : idée 1 + histoire 2 + script 2 +
référence 12 + métadonnées 1 + 10 × (voix 4 + clip 7) = **128 crédits** en Rapide (138 en Équilibré, 198 en Précision, 238
en Maximum). Les 200 crédits d'inscription la paient avec de la marge ; `GET /api/billing` en déduit `videos_30s` par
forfait (Starter ≈ 9, Créateur ≈ 23, Pro ≈ 70). Packs : 500 crédits pour 6 $ et 1 500 pour 15 $ (crédit plus cher qu'en
forfait). `music`
et `montage` sont gratuits. Les montants invalides sont refusés en `400`.

## Aucun dollar devant un client
Un client ne voit que des crédits : cartes de modèles (`credits_per_clip`, `docs/settings-providers.md`), estimation des
clips (prix de la carte × scènes ; `GET /projects/{id}/estimate` renvoie `cost_usd: null`), projets (`credits_spent` :
crédits utilisés des réservations fermées + retenus des ouvertes ; `cost_usd`, `cost_by_step`, `budget_usd` nuls ; `meta.cost_usd` retiré des fichiers du projet) et
l'en-tête du projet (« Crédits utilisés : N », `CostSummary`). `GET /api/costs` et l'écran Coûts sont réservés à l'admin,
qui garde les dollars partout.

## Devis partagé : prix annoncé = prix facturé
`preflight_launch` valide un lancement sans effet de bord (état des étapes, modèle, reprise, devis). `launch_step` et
`POST …/steps/{name}/price` l'appellent tous deux : le prix affiché est exactement le montant réservé. Reprise (`resume`)
et `only_missing` ne chiffrent que les scènes à générer ; une seule scène (`scene_id`), une scène.

## Cycle d'une génération (compte client)
1. **Lancement** : devis, limite de clips simultanés du forfait (`perks.parallel_clips`, `docs/abonnement.md` ; `409`), `reserve` (`409` « Crédits insuffisants : il vous faut N
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
