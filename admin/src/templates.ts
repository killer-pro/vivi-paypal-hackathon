/** Modèles de départ de l'accueil : formats de vidéos courtes qui fonctionnent, à compléter avec le sujet. */
export interface Template {
  id: string;
  name: string;
  /** Ce que produit le format, en une ligne. */
  hint: string;
  /** Texte du sujet ; `[sujet]` marque ce que l'utilisateur doit remplacer. */
  subject: string;
  duration_s: 15 | 30 | 60;
  /** `null` : durée des scènes libre, le script choisit. */
  scene_length_s: 3 | 5 | null;
}

export const PLACEHOLDER = "[sujet]";

export const TEMPLATES: Template[] = [
  {
    id: "tips",
    name: "3 astuces",
    hint: "Trois conseils concrets, un par scène",
    subject: `3 astuces pour ${PLACEHOLDER}, ton direct, public 18-30 ans`,
    duration_s: 30,
    scene_length_s: null,
  },
  {
    id: "fact",
    name: "Fait surprenant",
    hint: "Un fait que peu de gens connaissent, avec une chute",
    subject: `Un fait surprenant sur ${PLACEHOLDER} que presque personne ne connaît, avec une chute qui donne envie de partager`,
    duration_s: 30,
    scene_length_s: 3,
  },
  {
    id: "myth",
    name: "Idée reçue démontée",
    hint: "Ce qu'on croit, puis ce qui est vrai",
    subject: `Démonter une idée reçue sur ${PLACEHOLDER} : ce que tout le monde croit, puis ce qui est vrai`,
    duration_s: 30,
    scene_length_s: null,
  },
  {
    id: "story",
    name: "Histoire en 60 secondes",
    hint: "Un début accrocheur et une fin inattendue",
    subject: `Raconter en 60 secondes l'histoire de ${PLACEHOLDER}, avec un début qui accroche et une fin inattendue`,
    duration_s: 60,
    scene_length_s: 5,
  },
  {
    id: "news",
    name: "Actu en 15 secondes",
    hint: "Un sujet d'actualité, ton punchy, plans courts",
    subject: `L'essentiel à retenir sur ${PLACEHOLDER} en 15 secondes, ton punchy`,
    duration_s: 15,
    scene_length_s: 3,
  },
  {
    id: "before-after",
    name: "Avant / après",
    hint: "Une transformation montrée en deux temps",
    subject: `Avant / après : la transformation liée à ${PLACEHOLDER}, montrée en deux temps`,
    duration_s: 30,
    scene_length_s: 5,
  },
];

/** Plage (début, fin) du marqueur `[sujet]` dans le texte : sélectionnée à l'application du modèle pour être remplacée
 *  en tapant. `null` si le texte n'en contient plus. */
export function placeholderRange(subject: string): [number, number] | null {
  const start = subject.indexOf(PLACEHOLDER);
  return start === -1 ? null : [start, start + PLACEHOLDER.length];
}
