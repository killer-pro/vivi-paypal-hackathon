import { t } from "./i18n";
/** Modèles de départ de l'accueil : formats de vidéos courtes qui fonctionnent, à compléter avec le sujet. */
export interface Template {
  id: string;
  name: string;
  /** Ce que produit le format, en une ligne. */
  hint: string;
  /** Texte du sujet ; t("[sujet]") marque ce que l'utilisateur doit remplacer. */
  subject: string;
  duration_s: 15 | 30 | 60;
  /** `null` : durée des scènes libre, le script choisit. */
  scene_length_s: 3 | 5 | null;
}

export const PLACEHOLDER = t("[sujet]");

export const TEMPLATES: Template[] = [
  {
    id: "tips",
    name: t("3 astuces"),
    hint: t("Trois conseils concrets, un par scène"),
    subject: t("3 astuces pour {topic}, ton direct, public 18-30 ans", { topic: PLACEHOLDER }),
    duration_s: 30,
    scene_length_s: null,
  },
  {
    id: "fact",
    name: t("Fait surprenant"),
    hint: t("Un fait que peu de gens connaissent, avec une chute"),
    subject: t("Un fait surprenant sur {topic} que presque personne ne connaît, avec une chute qui donne envie de partager", { topic: PLACEHOLDER }),
    duration_s: 30,
    scene_length_s: 3,
  },
  {
    id: "myth",
    name: t("Idée reçue démontée"),
    hint: t("Ce qu'on croit, puis ce qui est vrai"),
    subject: t("Démonter une idée reçue sur {topic} : ce que tout le monde croit, puis ce qui est vrai", { topic: PLACEHOLDER }),
    duration_s: 30,
    scene_length_s: null,
  },
  {
    id: "story",
    name: t("Histoire en 60 secondes"),
    hint: t("Un début accrocheur et une fin inattendue"),
    subject: t("Raconter en 60 secondes l'histoire de {topic}, avec un début qui accroche et une fin inattendue", { topic: PLACEHOLDER }),
    duration_s: 60,
    scene_length_s: 5,
  },
  {
    id: "news",
    name: t("Actu en 15 secondes"),
    hint: t("Un sujet d'actualité, ton punchy, plans courts"),
    subject: t("L'essentiel à retenir sur {topic} en 15 secondes, ton punchy", { topic: PLACEHOLDER }),
    duration_s: 15,
    scene_length_s: 3,
  },
  {
    id: "before-after",
    name: t("Avant / après"),
    hint: t("Une transformation montrée en deux temps"),
    subject: t("Avant / après : la transformation liée à {topic}, montrée en deux temps", { topic: PLACEHOLDER }),
    duration_s: 30,
    scene_length_s: 5,
  },
];

/** Plage (début, fin) du marqueur t("[sujet]") dans le texte : sélectionnée à l'application du modèle pour être remplacée
 *  en tapant. `null` si le texte n'en contient plus. */
export function placeholderRange(subject: string): [number, number] | null {
  const start = subject.indexOf(PLACEHOLDER);
  return start === -1 ? null : [start, start + PLACEHOLDER.length];
}
