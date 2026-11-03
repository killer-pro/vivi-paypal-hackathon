# Journal des coûts et retries

## Vue d'ensemble

La fonction `tracked_call` enregistre chaque appel API à un provider externe dans la table `provider_calls` de la base de données. Elle gère automatiquement :

Chaque tentative est aussi envoyée à Langfuse Cloud si les clés sont renseignées (prompt, réponse, coût) : voir `langfuse.md`. Le paramètre `input` de `tracked_call` porte les messages envoyés (`langfuse.messages`).
- Les retries avec backoff exponentiel pour les erreurs `retryable`
- Les timeouts avec conversion en `ProviderError`
- Le logging des coûts USD et de la durée d'exécution
- Les écritures concurrentes : `tracked_call(..., writes=WriteGate)` passe l'écriture du journal par la porte d'écriture
  du pipeline quand plusieurs scènes sont générées en même temps (`docs/workflow-video.md`)

## Où et comment les montants s'affichent (source unique)
Tous les montants viennent de `provider_calls` et sont formatés par le même `usd` (`admin/src/format.ts`, dollars,
virgule décimale, 3 décimales au plus) ; les libellés disent « Dépensé » partout (plus de « Coût » ici et « Dépensé »
là).
- **Éditeur** (`components/CostSummary.tsx`) : « Dépensé 0,088 $ » discret ; au clic, détail par étape
  (`cost_by_step` de `GET /projects/{id}`, assistant IA regroupé, étapes à 0 $ omises), ce qui est compté et le plafond
  par vidéo (`budget_usd`). Le plafond n'apparaît en clair (« sur 10 $ », couleur d'alerte) qu'à partir de 80 % de
  consommation (`budgetState`, `BUDGET_WARNING`), jamais sans plafond.
- **Accueil** : le montant de la carte (`cost_usd`) n'apparaît que s'il est supérieur à 0 (une vidéo 100 % locale ne
  porte pas « 0 $ »), avec l'infobulle « Dépensé sur cette vidéo ».
- **Étape Clips** : estimation avant lancement, toujours préfixée « ≈ » ; locale : durée (ComfyUI), cloud : dollars
  calculés par l'API d'après la durée réelle des scènes (`GET /projects/{id}/estimate`).
- **Page Coûts** : totaux du journal, filtrables (période, projet, provider).
- Les totaux arrondis par ligne peuvent différer d'un millième du total (chaque montant est arrondi à 3 décimales).

## Coût de revient et prix en crédits
Les montants de ce document sont des **coûts de revient** en dollars. Le client paie un **prix en crédits** (coût × marge, arrondi au supérieur) : voir `docs/credits.md`. Le budget en dollars ci-dessous ne s'applique qu'aux projets du compte administrateur ; pour un client, les crédits font office de budget.

## Budget par projet

Réglage `project_budget_usd` (Réglages > Choix par défaut ; défaut 10 $, `0` = sans limite, virgule décimale acceptée).
Code : `backend/app/services/budget.py`. `launch_step` (API et worker) le contrôle avant de passer l'étape à `running` :
- étapes payantes seulement (`idea`, `script`, `reference`, `clips`, `voice`, `final`) ; `music` et `montage` sont
  gratuites : un projet au budget atteint peut toujours les terminer ;
- refus (`409`, `BudgetExceeded`) si dépenses du projet (`Σ provider_calls.cost_usd`) + coût estimé à venir > budget ;
  le coût à venir n'est estimé que pour `clips` (en reprise ou pour les scènes manquantes, seulement les scènes qui seront générées) (`estimate_cost` du provider, une seule scène si `scene_id`), les autres
  étapes coûtent quelques centimes ;
- en mode automatique, l'étape qui dépasserait le budget passe en `failed` avec le message (« Budget de la vidéo
  atteint : … Relevez le budget dans Réglages »), l'autopilot s'arrête, un événement SSE est publié ; relancer l'étape
  après avoir relevé le budget reprend normalement.

## Utilisation

```python
from app.services.costs import tracked_call

result = await tracked_call(
    session,
    project_id=project.id,
    step="video_generation",
    provider="fal.ai",
    model="flux",
    fn=lambda: provider.generate("prompt"),
    attempts=3,
    base_delay=1.0,
    timeout=600
)
```

## Comportement

- **Succès** : crée une ligne `provider_calls` avec `status="ok"` et le coût USD du résultat
- **Erreur non-retryable** : crée une ligne `provider_calls` avec `status="error"` et lève l'exception
- **Erreur retryable** : crée une ligne `provider_calls` avec `status="error"`, puis réessaye avec attente exponentielle (1s, 2s, 4s, ...)
- **Timeout** : convertit `asyncio.TimeoutError` en `ProviderError("timeout", retryable=False)` et enregistre l'erreur

## Paramètres

- `session` : session SQLAlchemy async
- `project_id` : ID du projet (optionnel, peut être `None`)
- `step` : nom de l'étape (ex. "clips", "music", "voice") ; `assist:<champ>` pour l'assistant IA de l'admin
  (ex. `assist:voice_text`, `project_id` vide à la création d'un projet)
- `provider` : nom du provider (ex. "fal.ai", "elevenlabs")
- `model` : identifiant du modèle utilisé
- `fn` : fonction async qui effectue l'appel (doit retourner un objet avec `.cost_usd`)
- `attempts` : nombre de tentatives max (défaut 3)
- `base_delay` : délai initial en secondes (défaut 1.0)
- `timeout` : timeout en secondes (défaut 600)

## Coût des appels LLM

- Claude : `input_tokens` x `PRICE_IN_PER_M` + `output_tokens` x `PRICE_OUT_PER_M` (`providers/claude.py`), par million.
- Gemini : `promptTokenCount` x prix d'entrée + (`candidatesTokenCount` + `thoughtsTokenCount`) x prix de sortie, par
  million, selon la table `PRICES` de `providers/gemini.py` (les tokens de réflexion sont facturés comme de la sortie ;
  modèle absent de la table = prix le plus élevé de la table). Sans `candidatesTokenCount`, la sortie vaut
  `totalTokenCount - promptTokenCount` ; un compteur absent ou `null` compte 0. Avertissement dans les logs si la table
  a dépassé `PRICES_VALID_UNTIL`. La ligne `provider_calls` porte `provider="gemini"` et
  le modèle utilisé (`gemini_model`).
