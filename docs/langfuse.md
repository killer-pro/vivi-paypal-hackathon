# Journal des appels IA (Langfuse Cloud)

Chaque appel à un provider (texte, image, vidéo, voix) est tracé dans [Langfuse Cloud](https://cloud.langfuse.com) en plus du journal local `provider_calls` : prompt envoyé, réponse, tokens, coût, durée, erreur. Langfuse sert à relire et comparer les prompts ; le **budget** et les **cartes de coût** restent calculés depuis `provider_calls` (la base reste la source de vérité).

## Activation
Variables de `backend/.env` ou écran Providers → Langfuse (la base prime) :
- `LANGFUSE_PUBLIC_KEY` (`pk-lf-…`) et `LANGFUSE_SECRET_KEY` (`sk-lf-…`, chiffrée en base) ;
- `LANGFUSE_BASE_URL` : vide = `https://cloud.langfuse.com` (région UE) ; `https://us.cloud.langfuse.com` pour la région US ; ou une instance auto-hébergée.
**Sans les deux clés, rien n'est envoyé.** L'API et le worker lisent le `.env` au démarrage : les redémarrer après modification (les réglages de l'écran sont relus à chaque appel). Le badge « Connecté » vient de `GET /api/providers/health` (clé `langfuse` : clés acceptées par `GET /api/public/projects`).

## Structure d'une trace
Suit la page [« What does a good trace look like? »](https://langfuse.com/docs/observability/best-practices) de Langfuse. Code : `backend/app/services/langfuse.py`, SDK officiel Python (`langfuse>=5`, OpenTelemetry).

| Niveau | Quoi | Détail |
|---|---|---|
| **Session** | un projet | `session_id = projet-<id>` : toutes les étapes du projet, dans l'ordre |
| **Trace** | un lancement d'étape | observation racine `run-<étape>` (`services/pipeline.py::run_step`) ; entrée = titre du projet + étape (+ `scene_id`), sortie = statut et erreur ; tag = l'étape |
| **Generation** | une tentative d'appel provider | `tracked_call` : les retries comptent chacun ; enfant de la racine |

Un appel hors étape (assistant d'écriture, chat du plan) n'a pas de racine : sa generation est sa propre trace, dans la session du projet s'il y en a un.

**Noms** stables, verbe d'abord, sans identifiant ni modèle (ils servent de filtres aux évaluateurs et aux tableaux de bord) : `write-idea`, `write-story`, `write-script`, `generate-reference`, `generate-clip`, `synthesize-voice`, `write-metadata`, `chat-plan`, `assist-<type>` (table `ACTIONS`). Les valeurs propres à l'exécution (fournisseur, étape, tentative, projet) sont en **métadonnées**. L'environnement Langfuse est `APP_ENV` (`dev` en local).

**Contenu d'une generation** : `model`, entrée en **messages** `system`/`user` (affichés comme une conversation), sortie `{"role": "assistant", …}`, `usage_details` (tokens d'entrée et de sortie : Claude `usage`, Gemini `usageMetadata`), `cost_details.total` (notre coût en dollars, plus exact que la table de prix de Langfuse pour les images et vidéos), niveau `ERROR` + message en cas d'échec. Un média (image, vidéo, voix) n'est **jamais** envoyé : seulement `{content_type, bytes}`. Les textes sont coupés à 20 000 caractères.

**Confidentialité** : prompts et réponses (idées, scripts, texte de voix) sortent vers un service tiers. Ne pas renseigner les clés pour garder tout en local.

## Garanties
- Le SDK envoie en arrière-plan : une panne de Langfuse ne retarde ni ne fait échouer une étape (avertissements dans les logs).
- `langfuse.shutdown()` vide la file d'envoi à l'arrêt de l'API (`main.py`) et du worker (`worker.py`).
- Les clés sont relues à chaque appel ; un client du SDK est créé par jeu de clés (`client_for`).

## Pas encore couvert
- `user_id` : à renseigner avec les comptes utilisateurs (chantier SaaS), pour le coût par client.
- La réflexion (thinking) des modèles n'est pas capturée (Gemini l'exclut du texte renvoyé).
- Médias en entrée/sortie (`LangfuseMedia`) : images de référence et clips ne sont pas joints à la trace.
- Scores / évaluateurs (LLM-as-a-judge) et prompts gérés dans Langfuse.

## Vérifier une trace
Relire les observations récentes avec la CLI (les clés en variables d'environnement, `LANGFUSE_HOST` = `LANGFUSE_BASE_URL`) :
`npx langfuse-cli api observations list --from-start-time <ISO> --fields core,basic,io,model,usage,trace_context,metadata`.
(L'ancien `GET /api/public/traces` répond 410.)

## Tests
`backend/tests/test_langfuse.py` : le vrai SDK avec un exportateur en mémoire (aucun réseau) — désactivé sans clés, generation (messages, tokens, coût, session, tags), média décrit sans être envoyé, une generation d'erreur par tentative, racine `run-<étape>` parente des generations, noms stables, coupe des textes, arrêt, contrôle des clés.
