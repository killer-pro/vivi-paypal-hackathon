// Contenu et logique pure de la page de présentation (`/decouvrir`) ; les visuels sont dans `public/landing/`
// (générés par `backend/scripts/gen_landing_assets.py`).

export type SceneId = "sneaker-packshot" | "sneaker-detail" | "sneaker-street";

export const SCENE_IDS: SceneId[] = ["sneaker-packshot", "sneaker-detail", "sneaker-street"];

/** Image large (16:9) d'une étape du pipeline ou de la conclusion, dans `public/landing/`. */
export const wide = (name: string) => `/landing/wide-${name}.jpg`;

/** Affiche ou clip vertical (9:16) d'une scène, dans `public/landing/`. */
export const clip = (name: string, ext: "jpg" | "mp4") => `/landing/${name}.${ext}`;

export const SCENES: Record<SceneId, { title: string; line: string }> = {
  "sneaker-packshot": { title: "Le produit", line: "La basket en suspension, sous la lumière du studio." },
  "sneaker-detail": { title: "Le détail", line: "Une goutte glisse sur la maille, la caméra se rapproche." },
  "sneaker-street": { title: "Dans la rue", line: "Une coureuse traverse la ville au coucher du soleil." },
};

/** Cas d'usage montrés dans la page : un clip vertical chacun (`art` = nom du fichier dans `public/landing/`). */
export const USE_CASES = [
  { name: "Produit", art: "sneaker-packshot", line: "Lancement d'un produit, du packshot à la rue." },
  { name: "Immobilier", art: "immobilier", line: "La visite d'un appartement avant la première visite." },
  { name: "Restauration", art: "restaurant", line: "Le geste du chef, la vapeur, l'assiette." },
  { name: "Mode", art: "mode", line: "Une collection qui bouge, tissu compris." },
  { name: "Voyage", art: "voyage", line: "Une destination qui donne envie de réserver." },
  { name: "Application", art: "app", line: "Une démo d'app qui se comprend en trois secondes." },
];

/** Styles visuels pour TikTok, YouTube Shorts et Reels : le même outil, des univers très différents. */
export const STYLES = [
  { name: "Anime", art: "style-anime", line: "Un décor dessiné à la main, cheveux et écharpe au vent." },
  { name: "Animation 3D", art: "style-pixar", line: "Un personnage de film d'animation, expressif et doux." },
  { name: "Rétro VHS", art: "style-vhs", line: "Le grain et le tremblé d'un caméscope des années 90." },
  { name: "Cyberpunk", art: "style-cyberpunk", line: "Néons, pluie et reflets pour un clip qui accroche." },
  { name: "Pâte à modeler", art: "style-claymation", line: "Du stop-motion artisanal, empreintes comprises." },
  { name: "Aquarelle", art: "style-aquarelle", line: "Des lavis de couleur qui bougent comme du papier mouillé." },
];

/** Formats de contenu qui marchent en vertical, chacun avec son clip. */
export const FORMATS = [
  { name: "ASMR", art: "asmr", line: "Un geste satisfaisant, en gros plan." },
  { name: "Histoires", art: "mystere", line: "Un récit à suspense, raconté en voix off." },
  { name: "Motivation", art: "sport", line: "L'effort, la sueur, la musique qui monte." },
  { name: "Street food", art: "street-food", line: "Flammes, vapeur et wok." },
  { name: "Culture et sciences", art: "science", line: "L'espace, expliqué en soixante secondes." },
  { name: "Musique", art: "concert", line: "Lasers, foule et refrain." },
];

/** Tous les clips verticaux : le mur de l'accroche les répartit en colonnes sans en répéter un seul. */
const WALL_CLIPS = [
  "style-anime", "sneaker-packshot", "mystere", "voyage", "style-cyberpunk", "chiot",
  "restaurant", "style-pixar", "fantasy", "mode", "asmr", "auto",
  "style-vhs", "immobilier", "sport", "style-claymation", "beaute", "science",
  "app", "street-food", "style-aquarelle", "sneaker-street", "concert", "sneaker-detail",
];

/** Colonnes du mur de clips de l'accroche : chacune dérive à son rythme, dans un sens puis dans l'autre. */
export const WALL: string[][] = Array.from({ length: 6 }, (_, c) => WALL_CLIPS.filter((_, i) => i % 6 === c));

/** Déplace une scène d'un cran dans l'ordre de lecture ; sans effet aux extrémités. */
export function moveScene(order: SceneId[], id: SceneId, delta: -1 | 1): SceneId[] {
  const from = order.indexOf(id);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= order.length) return order;
  const next = [...order];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}

/** Scène jouée après `current`, en reprenant au début après la dernière. */
export function nextScene(order: SceneId[], current: SceneId): SceneId {
  return order[(order.indexOf(current) + 1) % order.length];
}

export const PIPELINE = [
  { name: "Idée", art: "idee", does: "Un produit, un lieu, une phrase. L'assistant propose des pistes." },
  { name: "Script", art: "script", does: "Une histoire découpée en scènes que vous relisez et modifiez." },
  { name: "Références", art: "references", does: "Produit, personnage et décor restent identiques d'une scène à l'autre." },
  { name: "Clips", art: "clips", does: "Chaque scène devient un clip, en local avec ComfyUI ou par API." },
  { name: "Voix", art: "voix", does: "Une voix off générée par ElevenLabs." },
  { name: "Musique", art: "musique", does: "Un morceau de votre bibliothèque, ou le vôtre." },
  { name: "Montage", art: "montage", does: "FFmpeg assemble clips, voix, musique et sous-titres." },
  { name: "Export", art: "export", does: "Une vidéo 9:16 prête à publier, avec ses métadonnées." },
];

export const STRENGTHS = [
  {
    title: "Local d'abord",
    text: "Wan 2.2 tourne sur votre machine via ComfyUI, en quatre profils, du plus rapide au plus net. Les clips ne sont pas facturés à la seconde.",
  },
  {
    title: "Coûts sous contrôle",
    text: "Chaque appel à un fournisseur est journalisé, et un plafond de coût s'applique à chaque projet.",
  },
  {
    title: "Scènes indépendantes",
    text: "Une scène n'a pas besoin de la précédente : réordonnez, supprimez ou régénérez-en une seule.",
  },
  {
    title: "Vos fournisseurs",
    text: "Claude ou Gemini pour le texte, Gemini ou fal.ai pour les images, ElevenLabs pour la voix. Changez-les dans Réglages.",
  },
];

/** Idées proposées sous la barre de la page : un clic remplit le champ. */
export const IDEA_EXAMPLES = [
  "Lancement d'une basket running, du packshot à la rue",
  "3 astuces pour mieux dormir, ton direct",
  "Visite d'un T3 lumineux à Lyon",
  "Une histoire à suspense dans un phare abandonné",
];
