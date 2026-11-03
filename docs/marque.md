# Marque

## Nom
**Vivi**, contraction de « **vi**déo **vi**rale ». S'écrit « Vivi » dans les textes, jamais « VIVI ».

## Logo
Un V (l'initiale de Vivi) au trait épais et arrondi, aux branches inégales (la droite monte plus haut, comme une
courbe qui décolle), en dégradé rose → violet (branche gauche) et jaune → orange → rose → violet (branche droite), avec une étincelle
jaune. Généré avec Gemini (web), puis redessiné en SVG ; le mot « Vivi » n'est pas dans le fichier, il s'affiche à côté. Les deux logos précédents (triangle pointe en bas, V découpé dans un cadre 9:16) ont été
abandonnés : le premier se lisait comme une flèche « descendre », le second manquait de caractère.

`admin/public/favicon.svg` est l'unique source : l'onglet du navigateur l'utilise directement, et la classe `.brand-mark`
(`admin/src/index.css`) l'affiche dans la barre latérale, la connexion et la landing.

## Identifiants techniques conservés
Le nom interne `video_virale` / `video-virale` reste pour le dépôt, le projet Compose, la base de données, le bucket MinIO,
le paquet Python et les préfixes de sortie ComfyUI : ils ne sont pas visibles des clients et les renommer imposerait de
migrer des données.

## Vérifications à faire avant lancement public
- Disponibilité de la marque à l'INPI et à l'EUIPO (classes 9 et 42) : des produits proches existent (Vivideo.ai,
  VivaVideo, ViviPic, une fiche « Vivi AI »).
- Domaine : `vivi.*` est pris ; piste `vivistudio.com` / `vivistudio.fr`, à confirmer chez un registrar.
