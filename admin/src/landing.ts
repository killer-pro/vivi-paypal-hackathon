import { t } from "./i18n";
// Contenu et logique pure de la page de présentation (`/decouvrir`) ; les visuels sont dans `public/landing/`
// (générés par `backend/scripts/gen_landing_assets.py`).

export type SceneId = "sneaker-packshot" | "sneaker-detail" | "sneaker-street";

export const SCENE_IDS: SceneId[] = ["sneaker-packshot", "sneaker-detail", "sneaker-street"];

/** Image large (16:9) d'une étape du pipeline ou de la conclusion, dans `public/landing/`. */
export const wide = (name: string) => `/landing/wide-${name}.jpg`;

/** Affiche ou clip vertical (9:16) d'une scène, dans `public/landing/`. */
export const clip = (name: string, ext: "jpg" | "mp4") => `/landing/${name}.${ext}`;

export const SCENES: Record<SceneId, { title: string; line: string }> = {
  "sneaker-packshot": { title: t("Le produit"), line: t("La basket en suspension, sous la lumière du studio.") },
  "sneaker-detail": { title: t("Le détail"), line: t("Une goutte glisse sur la maille, la caméra se rapproche.") },
  "sneaker-street": { title: t("Dans la rue"), line: t("Une coureuse traverse la ville au coucher du soleil.") },
};

/** Cas d'usage montrés dans la page : un clip vertical chacun (`art` = nom du fichier dans `public/landing/`). */
export const USE_CASES = [
  { name: t("Produit"), art: "sneaker-packshot", line: t("Lancement d'un produit, du packshot à la rue.") },
  { name: t("Immobilier"), art: "immobilier", line: t("La visite d'un appartement avant la première visite.") },
  { name: t("Restauration"), art: "restaurant", line: t("Le geste du chef, la vapeur, l'assiette.") },
  { name: t("Mode"), art: "mode", line: t("Une collection qui bouge, tissu compris.") },
  { name: t("Voyage"), art: "voyage", line: t("Une destination qui donne envie de réserver.") },
  { name: t("Application"), art: "app", line: t("Une démo d'app qui se comprend en trois secondes.") },
];

/** Styles visuels pour TikTok, YouTube Shorts et Reels : le même outil, des univers très différents. */
export const STYLES = [
  { name: "Anime", art: "style-anime", line: t("Un décor dessiné à la main, cheveux et écharpe au vent.") },
  { name: t("Animation 3D"), art: "style-pixar", line: t("Un personnage de film d'animation, expressif et doux.") },
  { name: t("Rétro VHS"), art: "style-vhs", line: t("Le grain et le tremblé d'un caméscope des années 90.") },
  { name: "Cyberpunk", art: "style-cyberpunk", line: t("Néons, pluie et reflets pour un clip qui accroche.") },
  { name: t("Pâte à modeler"), art: "style-claymation", line: t("Du stop-motion artisanal, empreintes comprises.") },
  { name: t("Aquarelle"), art: "style-aquarelle", line: t("Des lavis de couleur qui bougent comme du papier mouillé.") },
];

/** Formats de contenu qui marchent en vertical, chacun avec son clip. */
export const FORMATS = [
  { name: "ASMR", art: "asmr", line: t("Un geste satisfaisant, en gros plan.") },
  { name: t("Histoires"), art: "mystere", line: t("Un récit à suspense, raconté en voix off.") },
  { name: t("Motivation"), art: "sport", line: t("L'effort, la sueur, la musique qui monte.") },
  { name: "Street food", art: "street-food", line: t("Flammes, vapeur et wok.") },
  { name: t("Culture et sciences"), art: "science", line: t("L'espace, expliqué en soixante secondes.") },
  { name: t("Musique"), art: "concert", line: t("Lasers, foule et refrain.") },
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
  { name: t("Idée"), art: "idee", does: t("Un produit, un lieu, une phrase. L'assistant propose des pistes.") },
  { name: t("Script"), art: "script", does: t("Une histoire découpée en scènes que vous relisez et modifiez.") },
  { name: t("Références"), art: "references", does: t("Produit, personnage et décor restent identiques d'une scène à l'autre.") },
  { name: t("Clips"), art: "clips", does: t("Chaque scène devient un clip, en local avec ComfyUI ou par API.") },
  { name: t("Voix"), art: "voix", does: t("Une voix off générée par ElevenLabs.") },
  { name: t("Musique"), art: "musique", does: t("Un morceau de votre bibliothèque, ou le vôtre.") },
  { name: t("Montage"), art: "montage", does: t("FFmpeg assemble clips, voix, musique et sous-titres.") },
  { name: t("Export"), art: "export", does: t("Une vidéo 9:16 prête à publier, avec ses métadonnées.") },
];

export const STRENGTHS = [
  {
    title: t("Local d'abord"),
    text: t("Wan 2.2 tourne sur votre machine via ComfyUI, en quatre profils, du plus rapide au plus net. Les clips ne sont pas facturés à la seconde."),
  },
  {
    title: t("Coûts sous contrôle"),
    text: t("Chaque appel à un fournisseur est journalisé, et un plafond de coût s'applique à chaque projet."),
  },
  {
    title: t("Scènes indépendantes"),
    text: t("Une scène n'a pas besoin de la précédente : réordonnez, supprimez ou régénérez-en une seule."),
  },
  {
    title: t("Vos fournisseurs"),
    text: t("Claude ou Gemini pour le texte, Gemini ou fal.ai pour les images, ElevenLabs pour la voix. Changez-les dans Réglages."),
  },
];

/** Idées proposées sous la barre de la page : un clic remplit le champ. */
export const IDEA_EXAMPLES = [
  t("Lancement d'une basket running, du packshot à la rue"),
  t("3 astuces pour mieux dormir, ton direct"),
  t("Visite d'un T3 lumineux à Lyon"),
  t("Une histoire à suspense dans un phare abandonné"),
];
