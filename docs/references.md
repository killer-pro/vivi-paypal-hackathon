# Images de référence par élément

Un personnage ou un produit qui revient d'une scène à l'autre garde la même apparence si chaque clip part de **son**
image (Flux Kontext replace l'élément dans la scène, puis Wan 2.2 I2V l'anime : voir `docs/profils-generation.md`).

## Flux
1. **Script** : l'IA renvoie, en plus de `bible` et `scenes`, `references` (au plus `MAX_REFERENCES` = 6 éléments
   récurrents : `id` court, `prompt` d'image sujet seul sur fond neutre, marque nommée et logo décrit, `descriptor` : apparence physique en anglais, 40 mots au plus) et, par scène,
   `reference` (id de l'élément principal visible, ou vide). Stockés dans `steps.result.references` (étape script) et
   `scenes.reference` (migration `0009`). Un id inconnu d'une scène est ramené à vide ; ids normalisés par `ref_id`.
   **Cohérence garantie par le serveur** (`apply_descriptors`) : le prompt visuel d'une scène qui a une référence doit commencer par
   son `descriptor` ; si le LLM l'a oublié ou paraphrasé (comparaison sans casse ni ponctuation), le serveur l'ajoute en tête
   du prompt enregistré (visible et modifiable). Sans `descriptor` (anciens projets), rien ne change.
2. **Étape reference** (facultative) : lancée **dès que le script est écrit**, pendant sa relecture (`can_start` accepte un script `awaiting_validation` ; `start_reference_after_script`, appelée par le worker en fin de job `script`, si le script liste des éléments, que `reference` est `pending`/`stale` et que l'autopilot est éteint ; avec l'autopilot, `advance` la lance), ou à la validation du script (`POST …/steps/script/approve` appelle la même fonction, qui accepte aussi un script `approved`) si elles n'existent pas encore : `reference` `pending` (lancement refusé plus tôt, par exemple par le budget depuis relevé) ou `stale` (élément ajouté, retiré ou modifié via `PATCH …/steps/script`). Une étape `failed` n'est pas relancée (« Réessayer » reste à l'utilisateur). Comme `/run`, l'API ne fait qu'enfiler le job et publie l'événement `running`. Un refus du lancement (budget, générateur indisponible, file) est silencieux : le script reste à valider (ou validé, sans erreur) et `reference` reste lançable à la main. Le plafond de budget est vérifié avant le lancement, mais le coût des images de référence n'est pas estimé : une rafale de 6 à 12 images au plus (0 $ avec ComfyUI) peut le dépasser légèrement. Les clips lancés pendant que les images de référence se génèrent attendent leur fin dans la file (`file-attente.md`) : ils lisent ces images au démarrage. Changer le texte du plan ne périme pas ces images tant que les éléments du script ne changent pas (`script_stale_names`). Une image par élément (`_reference`), au prompt
   du script ou de `params.prompts[id]` (modifié dans l'admin), + `reference_suffix(project)` (fond neutre, style du projet).
   Asset `reference` avec `meta.ref = id`. `reference_id` au lancement ne (re)génère qu'un élément. Sans élément dans le
   script (anciens projets) : l'image unique d'avant, d'après la fiche visuelle.
3. **Clips** : chaque scène prend l'image de son élément (`_reference_images`), à défaut l'image du projet (asset sans
   `meta.ref`, ex. import), sinon texte seul. Une référence principale par scène, plus d'autres éléments dont l'image part avec elle (`scene.elements`, 2 images au plus au total, personnages d'abord : `extra_references`). Une scène « continue » prend la dernière image du clip précédent comme principale ; si son sujet (`scene.reference`) n'était pas dans la scène précédente, sa référence part parmi les autres images.

## API
- `PUT /projects/{id}/scenes/{scene_id}/reference` `{reference, elements?}` : élément principal de la scène (`""` : aucun) et, si `elements` est donné, la liste complète des éléments dont l'image part avec le clip, principale comprise (l'admin envoie toutes les cases cochées ; `state` conservé ; omis : inchangés) ; 422 si plus de 2 images en tout ou si l'élément
  n'est pas dans le script, autorisé pendant les clips (vaut pour les scènes pas encore démarrées). Le clip déjà produit n'est pas touché : à régénérer.
- `POST /projects/{id}/reference/upload` (multipart) : champ `ref` facultatif, pour importer l'image d'un élément. Autorisé
  pendant les clips (le job a lu ses images au lancement ; la nouvelle sert aux clips suivants), 409 pendant l'étape
  reference.
- `POST /projects/{id}/references` `{name, prompt, story_id?}` : ajoute (avec `story_id`, un élément de l'histoire sans image — accessoire au-delà du plafond, lieu — est promu en référence : il garde son id et son descripteur, 422 s'il n'existe pas dans l'histoire) un élément aux `references` du script (id tiré du nom, sans
  accents). 201 `{id, prompt}` ; 409 si le script tourne ou n'existe pas, si l'id existe ou si `MAX_REFERENCES_TOTAL` (12, contre 6 générés d'office par l'IA) est atteint ;
  422 si le nom est inexploitable. Rien n'est périmé ; un nouveau script remplace la liste.
- `POST …/steps/reference/run` : `reference_id` (422 sur une autre étape) et `params` (prompts, générateur) appliqués au démarrage ; un élément seul demandé pendant que l'étape tourne est mis en file (`file-attente.md`), l'étape entière reste un 409.
- `PATCH …/steps/script` : une scène sans `reference` la conserve ; `""` la retire.

## Admin
Les images apparaissent dès que le script est écrit (événement `reference` `running` publié par le worker, ou par l'API à la validation du script), sans action de l'utilisateur.
Les images sont toujours visibles en tête des onglets Script et Clips de la page projet, dans le même bandeau que l'écran Plan
(`CastStrip` sur `castOf` : vignette 9:16, type, nombre de scènes, « Générer » / « Réessayer » d'un seul élément) ; chaque ligne
de la liste des scènes porte les pastilles de ses éléments (avec leur état) et un trait d'accent relie les scènes enchaînées.
Clips → « Image de référence » (replié : il ne sert qu'à modifier) : une carte par élément (nom, scènes qui l'utilisent, prompt modifiable, Importer, Générer / Régénérer) et
« Générer toutes les images » ; « + élément de l'histoire » promeut en référence un élément de l'histoire qui n'en a pas (prompt de son image, à défaut sa description) ; « Ajouter un élément » (nom + description) crée un personnage ou un objet en plus de
ceux du script, puis on l'attribue aux scènes ; sous chaque scène, une seule liste « Images envoyées avec le clip » (case + miniature + nom par élément, 2 images au plus ; en cocher une de plus retire la plus ancienne). La première cochée est l'image principale (`reference` de la scène) ; toutes les cochées sont envoyées comme `elements` (la principale y reste, comme à l'écriture du script : son état est conservé et sa pastille reste affichée). Un accessoire coché en image secondaire compte aussitôt la scène dans le casting. Générer une référence périme les étapes
aval (clips, voix, montage), comme tout changement d'une étape amont.

## Limites
La référence donne l'identité (visage, tenue, produit, logo), pas la pose : Kontext replace l'élément dans la scène.
Chaque scène avec référence ajoute l'étape Kontext avant Wan (voir les mesures de `docs/profils-generation.md`).

## Enchaînement des scènes (`continuity`)
Case « Enchaîner » sous chaque scène de Clips (sauf la première) : `PUT /projects/{id}/scenes/{scene_id}/continuity`
`{continuity: "cut" | "continue"}` (422 pour la première scène). `continue` : la première image du clip est la dernière image
du clip sélectionné de la scène précédente (voir plus haut). **Verrou** : régénérer seule une scène `continue` dont la
précédente n'a aucun clip sélectionné est refusé (`409`, bouton grisé avec la raison dans l'admin, `chainBlockedReason`).
Le clip déjà produit n'est pas touché par le changement.
