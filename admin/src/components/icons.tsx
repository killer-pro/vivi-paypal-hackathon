import type { ReactNode } from "react";

/** Icônes SVG inline (trait 1,75 px, couleur du texte). Décoratives : le libellé voisin porte le sens. */
function Icon({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

/** Cadres verticaux 9:16 : les vidéos du projet. */
export const ProjectsIcon = () => (
  <Icon>
    <rect x="3" y="3" width="7.5" height="13" rx="1.5" />
    <rect x="13.5" y="8" width="7.5" height="13" rx="1.5" />
  </Icon>
);

export const MusicIcon = () => (
  <Icon>
    <path d="M9 18V5l11-2v13" />
    <circle cx="6" cy="18" r="3" />
    <circle cx="17" cy="16" r="3" />
  </Icon>
);

const SLIDERS = (
  <>
    <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12" />
    <circle cx="16" cy="6" r="2" />
    <circle cx="10" cy="12" r="2" />
    <circle cx="18" cy="18" r="2" />
  </>
);

export const SettingsIcon = () => <Icon>{SLIDERS}</Icon>;

/** Réglage fin d'une action (consigne à l'assistant) : version 16 px des curseurs. */
export const TuneIcon = () => <Icon size={16}>{SLIDERS}</Icon>;

export const CostsIcon = () => (
  <Icon>
    <ellipse cx="12" cy="6" rx="7" ry="3" />
    <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
  </Icon>
);

export const CoinIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="8" />
    <path d="M14.5 9.5a3 3 0 1 0 0 5" />
  </Icon>
);

export const LogoutIcon = () => (
  <Icon>
    <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H3" />
  </Icon>
);

export const TrashIcon = () => (
  <Icon size={16}>
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />
  </Icon>
);

export const DownloadIcon = () => (
  <Icon size={16}>
    <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />
  </Icon>
);

/* Éditeur : outils du rail, en-tête et lecteur. */
/** Pellicule verticale : les clips 9:16. */
/** Pistes empilées : le montage assemble les pistes. */
export const BackIcon = () => (
  <Icon>
    <path d="M15 5l-7 7 7 7" />
  </Icon>
);

export const PlayIcon = () => (
  <Icon>
    <path d="M7 4.5v15l12-7.5z" fill="currentColor" />
  </Icon>
);

export const PauseIcon = () => (
  <Icon>
    <path d="M7 4.5h3.5v15H7zM13.5 4.5H17v15h-3.5z" fill="currentColor" />
  </Icon>
);

/* Actions courantes (16 px : s'alignent sur le texte d'un bouton). */
export const SearchIcon = () => (
  <Icon size={16}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-4.2-4.2" />
  </Icon>
);

export const PlusIcon = () => (
  <Icon size={16}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);

export const CheckIcon = () => (
  <Icon size={16}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Icon>
);


export const ChevronDownIcon = () => (
  <Icon size={16}>
    <path d="m6 9 6 6 6-6" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon size={16}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Icon>
);

export const ChevronRightIcon = () => (
  <Icon size={16}>
    <path d="m9 6 6 6-6 6" />
  </Icon>
);

/** Deux flèches en boucle : relancer une génération. */
export const RefreshIcon = () => (
  <Icon size={16}>
    <path d="M20 11a8 8 0 0 0-14.3-4M4 4v4h4M4 13a8 8 0 0 0 14.3 4M20 20v-4h-4" />
  </Icon>
);

export const StopIcon = () => (
  <Icon size={16}>
    <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
  </Icon>
);

export const UploadIcon = () => (
  <Icon size={16}>
    <path d="M12 16V5M7 9l5-5 5 5M5 20h14" />
  </Icon>
);

export const MicIcon = () => (
  <Icon size={16}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </Icon>
);




export const ChevronUpIcon = () => (
  <Icon size={16}>
    <path d="m6 15 6-6 6 6" />
  </Icon>
);

/** Baguette : demander une proposition à l'assistant. */
export const WandIcon = () => (
  <Icon size={16}>
    <path d="m5 19 10-10M14 6l4 4M17 3v3M15.5 4.5h3M7 3v2M6 4h2M20 14v2M19 15h2" />
  </Icon>
);

/** Cadre vertical avec lecture : l'aperçu de la vidéo. */
export const PreviewIcon = () => (
  <Icon>
    <rect x="6" y="3" width="12" height="18" rx="2.5" />
    <path d="M10.5 9.5v5l4-2.5z" fill="currentColor" />
  </Icon>
);

/** Lignes avec vignettes : le storyboard des scènes. */
export const ScenesIcon = () => (
  <Icon>
    <rect x="3" y="4" width="5" height="6" rx="1" />
    <rect x="3" y="14" width="5" height="6" rx="1" />
    <path d="M12 6h9M12 9h6M12 16h9M12 19h6" />
  </Icon>
);

const STAR = "m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.9z";

/** Étoile de notation : pleine, à moitié ou vide. */
export const StarIcon = ({ fill }: { fill: "full" | "half" | "empty" }) => (
  <svg width={14} height={14} viewBox="0 0 24 24" strokeLinejoin="round" aria-hidden>
    <path d={STAR} fill="none" stroke="currentColor" strokeWidth={1.75} />
    {fill !== "empty" && <path d={STAR} fill="currentColor" stroke="currentColor" strokeWidth={1.75} style={fill === "half" ? { clipPath: "inset(0 50% 0 0)" } : undefined} />}
  </svg>
);

export const ChevronLeftIcon = () => (
  <Icon size={16}>
    <path d="m15 6-6 6 6 6" />
  </Icon>
);

/** Étincelles : l'assistant IA. */
export const SparkleIcon = () => (
  <Icon>
    <path d="M10 3l1.8 4.7L16.5 9.5l-4.7 1.8L10 16l-1.8-4.7L3.5 9.5l4.7-1.8z" />
    <path d="M18 14l.8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8z" />
  </Icon>
);
