# File d'attente des générations

Une demande de génération qui tombe pendant qu'une autre bloque l'étape n'est plus refusée (409) : elle est gardée et
lancée dans l'ordre dès que plus rien ne la bloque. Comme la file de ComfyUI, mais par projet.

## Règles
- Bloque : l'étape elle-même en cours (ex. régénérer la scène 7 pendant que la scène 4 se génère) ou une étape qui en
  dépend (`dependents`, `app/state.py` : relancer le script pendant un montage). Voix et clips ne se bloquent pas : ils
  tournent en parallèle (le worker traite 2 jobs à la fois). Les clips attendent aussi la fin des images de référence
  (étape amont) : ils les lisent au démarrage et partiraient sinon sans elles.
- Maximum 5 demandes par projet ; la sixième reçoit `409 « File d'attente pleine »`. Une demande identique à une demande
  déjà en file n'est pas répétée.
- Relancer l'étape entière pendant qu'elle tourne reste un `409` (rien à attendre) ; un seul élément de référence (`reference_id`) se met en file.
- Les paramètres de l'étape reference (`params` : prompts, générateur) voyagent avec la demande et sont appliqués au démarrage : le `PATCH` des paramètres est refusé pendant que l'étape tourne.
- Les autres refus (étape précédente non validée, budget, modèle indisponible) restent immédiats au moment de la demande.

## Fonctionnement
- Table `queued_runs` (migration `0010`) : projet, étape, scène, options du lancement (`overrides`, `resume`,
  `only_missing`, `visual_prompt`).
- `services/queue_runs.py` : `run_or_queue` (route `POST …/run`), `dispatch_queue` (lance dans l'ordre ce qui n'est plus
  bloqué ; une demande devenue impossible est retirée et son motif publié dans l'événement du projet), `remove_queued`.
- `dispatch_queue` est appelé à la fin de chaque job du worker (réussi, échoué, expiré, arrêté), à l'arrêt d'une
  génération par l'API et au démarrage du worker (les demandes en file avant un redémarrage repartent).

## Interface
- Le bandeau d'activité au centre de l'en-tête affiche « N en attente » avec une flèche : un clic déplie la liste dans
  l'ordre de départ, chaque ligne se retire par une croix ; Échap ou un clic ailleurs referme.
- Pendant qu'une génération bloque l'étape, les boutons de lancement (scène, voix, étape) restent actifs et lisent
  « Mettre en file » ; ils se grisent quand la file est pleine (`QUEUE_MAX`, `studio.ts`).
