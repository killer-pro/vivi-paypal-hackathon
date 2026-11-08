# Page de présentation (`/decouvrir`)

Page publique (hors `Layout`, aucune session requise ; seul `GET /auth/me` est appelé pour adapter les boutons) qui montre le produit en quelques secondes : pour un jury de concours, un programme d'accélération ou un futur utilisateur. Elle reprend les jetons du thème « Studio » (`design-system.md`).

## Visiteur non connecté
- Un 401 sur un écran connecté (`api.ts`) renvoie vers `/decouvrir` (et non plus `/login`) : c'est la porte d'entrée. `/decouvrir` est dans `PUBLIC_PATHS` (`auth.ts`).
- En-tête : « Se connecter » et « S'inscrire » ; connecté, un seul bouton « Ouvrir l'application ».
- **Barre de recherche IA** (`IdeaBar`, accroche et conclusion) : champ « Décrivez votre vidéo… », quatre idées cliquables (`IDEA_EXAMPLES`) et « Créer ma vidéo ». L'idée est mémorisée (`pendingIdea.ts`, `localStorage`, clé `vivi.idee`, pour survivre au lien de confirmation e-mail) puis le visiteur va sur `/register` (connecté : `/new`).
- `/register` rappelle l'idée en attente. Après connexion (`Login`), une idée en attente envoie sur `/new`, où elle préremplit le champ « Votre idée » (effacée à la création du projet). Sans abonnement, `/new` affiche une invitation vers `/credits` (offres).
- Écrans de compte (`AuthCard`) : même mur de clips en fond (`components/ClipWall`, partagé avec l'accroche), carte translucide ; la marque renvoie à `/decouvrir`.

## Contenu
- **Accroche plein écran** : un mur de clips verticaux (six colonnes inclinées de 8°, qui dérivent à des vitesses différentes, une sur deux en sens inverse) couvre 24 clips différents, sans répétition ; le titre et la barre de création sont centrés sur un voile sombre. En défilant, le mur zoome et s'estompe, le texte s'efface.
- **Cas d'usage** : six clips 9:16 (produit, immobilier, restauration, mode, voyage, application), décalés une colonne sur deux. Un clip ne joue que lorsqu'il est à l'écran.
- **Styles et formats viraux** (`#styles`, « Pour TikTok, YouTube Shorts et Reels ») : deux rangées de six clips 9:16. Six styles (anime, animation 3D, rétro VHS, cyberpunk, pâte à modeler, aquarelle) et six formats (ASMR, histoires, motivation, street food, culture et sciences, musique).
- **Lecteur interactif** (`ScenePlayer`), titre à gauche et lecteur à droite : un téléphone 9:16 qui enchaîne les clips de trois plans d'une pub sneaker (« Le produit », « Le détail », « Dans la rue ») dans l'ordre choisi. Chaque scène se sélectionne, et les flèches la montent ou la descendent : la pub se remonte. À la fin du dernier clip, la lecture reprend au premier.
- **Carrousel du pipeline** : huit cartes (Idée à Export), une image par étape, défilement horizontal accroché carte par carte (doigt, molette, clavier une fois le carrousel focalisé, ou flèches).
- **Pensé pour tourner chez vous** : exécution locale (ComfyUI), plafond de coût, scènes indépendantes, choix des fournisseurs.
- **Conclusion plein cadre** sur l'image du lever de soleil.

## Animations et accessibilité
Toutes les animations vivent dans `@media (prefers-reduced-motion: no-preference)` : sans elles, le mur et les cartes restent sur l'affiche de leur clip, le lecteur ne démarre pas seul (contrôles natifs de la vidéo visibles) et le carrousel défile sans transition. Les effets liés au défilement (`animation-timeline: scroll()` et `view()`) sont en amélioration progressive derrière `@supports` : un navigateur qui ne les gère pas affiche la page sans eux.

## Code
- `admin/src/landing.ts` : textes, `USE_CASES`, `STYLES`, `FORMATS`, `WALL` (colonnes du mur, un clip une seule fois), `moveScene` (déplace une scène d'un cran, sans effet aux extrémités), `nextScene`, `clip` (affiche ou clip vertical) et `wide` (image large) ; testés dans `landing.test.ts`.
- `admin/src/pendingIdea.ts` (idée en attente, testé dans `pendingIdea.test.ts`), `components/ClipWall.tsx` (mur et `Clip`), `motion.ts`.
- `admin/src/pages/Landing.tsx` et `Landing.css` : toutes les classes sont préfixées `lp-` (le nom `.pipeline` existait déjà dans l'éditeur).
- Route `/decouvrir` dans `App.tsx`.

## Visuels
Les images et clips sont générés une fois et versionnés dans `admin/public/landing/` ; rien n'est généré à la visite.
- 24 scènes verticales en `.jpg` (9:16) et `.mp4` : `sneaker-packshot`, `sneaker-detail`, `sneaker-street` (le lecteur), `immobilier`, `restaurant`, `mode`, `voyage`, `app` (cas d'usage), `style-anime`, `style-pixar`, `style-vhs`, `style-cyberpunk`, `style-claymation`, `style-aquarelle`, `asmr`, `mystere`, `sport`, `fantasy`, `street-food`, `science`, `beaute`, `auto`, `chiot`, `concert`. Le mur les montre tous une fois (`WALL_CLIPS`), les sections en reprennent une partie.
- `wide-<nom>.jpg` (16:9) : une image par étape (`idee`, `script`, `references`, `clips`, `voix`, `musique`, `montage`, `export`) et `wide-conclusion`. Les huit images d'étape racontent un même film publicitaire (baskets turquoise, trench beige) et montrent ce que l'étape produit : croquis, storyboard, planche de personnage, pellicule, forme d'onde, mixage, timeline, téléphone. Générées avec Flux (voir `vivi-demo-video/tools/flux_images.py`).

`backend/scripts/gen_landing_assets.py` les produit, entièrement en local avec ComfyUI (aucune clé API) : images Flux dev (workflow `flux-keyframe`, 576×1008 ou 1024×576, converties en jpg avec `sips`), puis un clip de 3 s par scène verticale avec Wan 2.2 en profil « fast ». Compter environ 4 min par image et 8 min par clip. Le prompt de mouvement de chaque clip nomme chaque élément qui doit bouger (goutte, tissu, vapeur, vagues) : sans cela Wan n'anime que la caméra et laisse le reste figé. Les clips animent l'image telle quelle (Wan I2V direct) : `ComfyUIProvider.generate()` avec une image passerait d'abord par Kontext, qui la réinterprète. Un fichier déjà présent est sauté ; en supprimer un pour le régénérer. Pour d'autres scènes, modifier `SCENES`, `VIRAL` et `STEPS` dans le script, et `landing.ts` (`USE_CASES`, `STYLES`, `FORMATS`, `WALL_CLIPS`, `PIPELINE`).
