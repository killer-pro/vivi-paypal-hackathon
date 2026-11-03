/** Le visiteur a demandé moins de mouvement : les vidéos restent sur leur affiche. */
export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
