# Mode automatique (autopilot)

L'utilisateur donne un sujet et une durée ; le backend enchaîne seul idée → script → clips → voix → musique → montage
→ rendu final, valide chaque étape et s'arrête à la première erreur, si le budget du projet serait dépassé
(`docs/costs.md`, « Budget par projet ») ou si le modèle vidéo des clips est inconnu ou indisponible (« Clé fal
manquante », « ComfyUI injoignable », « Modèle manquant : <fichier> », même contrôle que `POST …/steps/clips/run`,
`services/video_models.py`) : l'étape refusée passe en `failed` avec la raison, sans job enfilé. Un ComfyUI qui ne
répond pas dans le délai (« ComfyUI ne répond pas (occupé ?) », ex. génération d'un autre projet) ne l'arrête pas :
les clips sont enfilés et attendent leur tour.

Code : `backend/app/services/steps.py` (lancement d'étape partagé, `start_autopilot`, `stop_autopilot`, `advance`),
`backend/app/worker.py` (appel de `advance` en fin de job), endpoints dans `backend/app/api/steps.py`.

## Drapeau
- Stocké dans `Project.metadata_json["autopilot"]` (pas de migration), présent seulement quand il est actif ;
  propriété `Project.autopilot` (lecture/écriture). `GET /projects/{id}` (et création/édition) exposent `autopilot: bool`.
- Les métadonnées publiées (étape `final`, exécuteur ou `PATCH` du résultat) remplacent `metadata_json` via
  `Project.replace_metadata`, qui conserve le drapeau.

## Autopilot borné (génération du plan)
`start_autopilot(..., until="story")` (ou `"script"` pour un projet existant dont la story est validée et vide : `plan_until`, `services/flow.py`) ajoute `autopilot_until` aux métadonnées (propriété `Project.autopilot_until`,
effacée avec le drapeau ; `replace_metadata` la conserve). `advance` s'arrête sur l'étape bornée : l'autopilot est coupé
et l'étape reste `awaiting_validation` (non validée), sans lancer la suivante. `POST /projects/{id}/plan/generate` → `202`
l'utilise (`409` si une étape tourne).

## Endpoints
- `POST /projects/{id}/autopilot` → `202` : exige qu'aucune étape ne tourne (`409` sinon), active le drapeau et lance
  `idea` (même chemin que `run` : l'aval déjà produit passe en `stale`). Redis indisponible → `503`, `idea` en
  `failed`, drapeau coupé.
- `DELETE /projects/{id}/autopilot` → `204` : coupe le drapeau. L'étape en cours finit (et reste `awaiting_validation`),
  la suite n'est pas lancée. `404` si le projet n'existe pas.

## Chaînage (worker)
À la fin de chaque job (`run_step_job`, hors timeout/annulation), `advance` s'exécute :
- autopilot inactif → rien (mode pas à pas) ;
- étape `awaiting_validation` → validée, puis lancement de l'étape suivante dans l'ordre du flow par `launch_step`
  (claim atomique, aval périmé, `job_timeout`, enqueue : la même fonction que l'API) et événement
  `{step: <suivante>, status: "running"}` ;
  - `reference` est ignorée (validée sans résultat) sauf si le script liste des éléments récurrents (`references`) : elle est alors générée (une image par élément, mascotte, produit, personnage) avant les clips, pour garder le même sujet d'une scène à l'autre ;
  - `music` : première piste de la bibliothèque (plus petit `id`) si aucune n'est choisie ; bibliothèque vide →
    étape exécutée sans piste (le montage fonctionne sans musique) ; un choix existant est conservé ;
  - `clips` : la première variante de chaque scène est sélectionnée d'office (voir `workflow-video.md`) ;
  - après `final` : validée, projet `done`, drapeau coupé, événement `{step: "final", status: "approved"}` ;
- étape `running` (relancée entre-temps) ou déjà `approved` (déjà enchaînée) → rien ;
- autre statut (`failed`, `stale`…) → drapeau coupé, l'étape reste relançable à la main.

Un job interrompu (timeout, arrêt du worker) ou une étape orpheline passée en `failed` au redémarrage du worker coupe
aussi l'autopilot de son projet (`fail_running_steps`). Un refus au lancement de l'étape suivante (409), budget ou
modèle vidéo refusé (400/409, l'étape passe en `failed` avec la raison) ou une file indisponible (503, l'étape passe
en `failed`) le coupe également.

## Après un échec
L'autopilot s'arrête sur l'étape en échec (drapeau coupé). La reprise (`resume` ou `only_missing`, `docs/workflow-video.md`)
se lance à la main depuis l'éditeur ; le reste du flow se poursuit pas à pas ou en relançant le mode automatique.

## Concurrence
Toute action qui lance une étape ou change le drapeau verrouille d'abord la ligne du projet (`SELECT … FOR UPDATE`,
`lock_project`) : lancements (API `run`, `POST /autopilot`), chaînage du worker, `DELETE /autopilot` et écriture des
métadonnées finales sont sérialisés par projet.
- Une étape n'est jamais lancée deux fois : la validation et le lancement de la suivante se font sous le verrou, et
  un second `advance` pour la même étape trouve la suite déjà lancée et ne fait rien ; le passage à `running` reste atomique.
- Après un `DELETE`, le worker relit le drapeau sous le verrou : rien n'est relancé. Si l'arrêt arrive juste après
  le lancement de l'étape suivante, celle-ci finit et rien n'est lancé après.
- L'exécuteur `final` relit le projet sous verrou avant d'écrire les métadonnées : un arrêt pendant l'appel au LLM
  n'est pas écrasé.

Si l'utilisateur valide une étape à la main juste avant que le worker ne l'enchaîne, `advance` la trouve `approved` et
lance quand même la suite, sauf si celle-ci est déjà lancée ou produite.
