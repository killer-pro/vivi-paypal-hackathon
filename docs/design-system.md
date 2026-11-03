# Design system de l'admin (V2)

Contrat visuel unique pour tous les écrans de `admin/`. Les jetons vivent dans `admin/src/index.css` (`:root`) ; ne pas
inventer de valeur locale : ajouter le jeton ici et dans `:root` d'abord.

## Direction
Un outil de montage vertical, dans la famille des éditeurs professionnels : le graphite neutre laisse la vidéo porter la couleur, l'interface n'en garde qu'une
(l'accent bleu-vert, réservé à l'action principale et à l'élément actif). Le modèle mental est un **storyboard de
scènes** produit par un pipeline (Idée → Script → Clips → Voix → Musique → Montage → Export), pas une boîte à outils libre.

## Couleurs
| Jeton | Valeur | Rôle |
|---|---|---|
| `--bg` | `#101214` | fond, champs de saisie |
| `--panel` | `#171a1d` | barres, panneaux, cartes |
| `--raised` | `#20252a` | survol, élément sélectionné, boutons |
| `--line` | `#2c3238` | filets |
| `--text` / `--muted` | `#e9ecef` / `#9aa3ab` | texte / texte secondaire |
| `--accent` (`-hover`, `-ink`) | `#22b8cf` (`#56cfe0`, `#061a1e`) | action principale, élément actif, focus |
| `--track-clip` / `-voice` / `-music` / `-subs` | `#8c9cff` / `#f0a35e` / `#c792ea` / `#e4e7ee` | type de média, jamais décoratif |
| `--st-*` | pending `#6b747c`, running = accent, awaiting `#f0c14b`, approved `#4cc38a`, failed `#ef6a64`, stale `#a99af5` | statut d'étape (`.st-*` → `--st`) |

## Surfaces et profondeur
Quatre niveaux, du plus enfoncé au plus flottant : `--bg` `#0d0f11` (fond, champs), `--panel` `#14171a` (barres, cartes),
`--raised` `#1b1f23` (survol, sélection, boutons), `--float` `#22272c` (menus et fenêtres flottantes). Filets `--line`
(`#252a2f`) et `--line-strong` (`#353c43`, contours de contrôles). `--faint` `#6b747c` pour placeholders et icônes
secondaires. `--accent-soft` (accent à 14 %) pour les halos de focus et les fonds de sélection. L'ombre (`--shadow-float`)
n'est réservée qu'aux éléments flottants (fenêtres, bulle de coût, lecteur) ; `--ease` et `--t-fast` (120 ms) pour toutes
les transitions.

## Typographie
Geist Variable (`@fontsource-variable/geist`), 14 px, chiffres tabulaires : neutre et lisible en petit, adaptée à des
durées, coûts et horodatages. Titres de page 22 px / 600 (interlettrage −0,02 em), titres de panneau 16 px, texte
secondaire 12–13 px. Sentence case, pas de capitales de remplissage, pas d'emoji : les titres de projet sont nettoyés à
l'affichage (`plainTitle`, `format.ts`).

## Logo
`admin/public/favicon.svg` (voir `marque.md`) : seule source du logo, utilisée comme favicon et par `.brand-mark` (32 × 32 px ; 48 px dans la barre latérale et 64 px sur les écrans de compte, avec « Vivi » en dessous).

## Icônes
Un seul jeu, `components/icons.tsx` : SVG inline, grille 24 px, trait 1,75 px, `currentColor`. 20 px pour la navigation, 16
px dans les boutons (le gap du bouton les espace du libellé). Toute action récurrente porte son icône : relancer
(`RefreshIcon`), arrêter (`StopIcon`), exporter (`DownloadIcon`), importer (`UploadIcon`), assistant (`WandIcon`). Les
notes sont des étoiles SVG (`StarIcon`), jamais des caractères. Ajouter une icône ici plutôt que d'en importer une
bibliothèque.

## Composants de base (`index.css` et `components/`)
- Boutons : `.btn` 34 px (`.btn-small` 28 px), variantes `.btn-primary`, `.btn-ghost`, `.btn-danger` (survol rouge),
  `.btn-icon` (carré, libellé en `aria-label`).
- Champs : `.input` 36 px, halo d'accent au focus ; `select.input` à flèche dessinée ; `.input-search` avec loupe.
- `Pills` : contrôle segmenté (rail + choix actif surélevé), `hideLegend` pour une légende réservée aux lecteurs d'écran.
- Volets repliables (`.advanced`, `.reprompt`) : chevron dessiné qui pivote à l'ouverture.
- `AudioPlayer` : lecteur compact remplaçant `<audio controls>`.
- `TextArea` : zone de saisie auto-extensible, compteur de caractères rouge à la limite (voir `docs/admin.md`).
- `PanelEdge` : bord réglable et repliable des colonnes de l'éditeur.
- `.spinner` : anneau qui tourne pour tout ce qui est en cours (figé si mouvement réduit). Un message d'état (`.notice`) n'a ni bordure colorée ni phrase d'explication : fond teinté par le statut, une ligne.
- Boutons radio des cartes de modèles : dessinés en CSS (le natif reste dans le DOM).

## Forme et mise en page
- Rayons : 6 px (`--radius-s`, contrôles), 10 px (`--radius-m`, cartes et surfaces), 14 px (`--radius-l`, fenêtres et
  panneaux flottants) ; pastilles en 999 px.
- Largeur de page : `--page-w` 1240 px (accueil, coûts, musique), `--page-w-narrow` 880 px (Réglages) ; centrées via
  `.main > *`. L'éditeur est plein cadre.
- Écran tactile (`pointer: coarse`) : boutons et champs d'au moins 40 px, compacts 32 px (36 px pour les pastilles, 40 px
  pour la suppression d'une carte).
- Petit écran (< 720 px hors éditeur, < 900 px dans l'éditeur) : navigation et volets en barre d'onglets fixée en bas.
- `.main > *` fixe la largeur de page ; une page plus étroite le surcharge avec `.main > .ma-page` (ex. `.composer`).
- Une seule action principale visible à la fois (`.btn-primary`). Statut dit par pastille + libellé, jamais par la
  couleur seule.

## Écran Plan
Grille `[chat ≈ 26 %] [plan] [Apparence ≈ 24 %]`, barre d'action en bas ; sous 860 px une seule colonne (plan,
Apparence, chat). Casting en vignettes 9:16 (`CastStrip`, `CastFrame` : image, sinon cadre en pointillés teinté par le
statut et pulsant pendant la génération). Carte de scène avec casting (`.scene-card.has-cast`) : vignette de l'élément
principal à gauche (64 px, 44 px sur mobile), pastilles d'éléments puis enchaînement ; une scène enchaînée
(`.is-chained`) est reliée à la précédente par un filet d'accent de 2 px à travers l'espace entre les cartes, en plus
du libellé « Enchaînée : … ». Génération du plan (`PlanProgress`) : étapes en liste numérotée, cercle et badge teintés
par le statut, anneau qui tourne et filet d'accent à gauche pour l'étape en cours. Phase histoire : sections titrées
avec compteur, comme le plan prêt ; section vide en cadre en pointillés (`.empty`). Détails : `docs/admin.md`.

## Éditeur
Grille `[scènes 252] [aperçu] [panneau 380]` sous la frise des étapes ; timeline en bas. Liste des scènes : pastilles
d'éléments sous chaque ligne, scènes enchaînées reliées par un trait d'accent de 2 px dans la marge gauche du rail. Les
onglets Script et Clips ouvrent sur le casting (`CastStrip`) ; cartes avec casting en vignette de 44 px. Détails :
`docs/admin.md`.
