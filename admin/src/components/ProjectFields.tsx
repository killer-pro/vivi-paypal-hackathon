import type { ProjectIn } from "../api";
import AssistField from "./AssistField";
import { Advanced, Field } from "./ui";
import TextArea from "./TextArea";
import { MAX_THEME } from "../limits";

const PLATFORMS = [
  { value: "tiktok", label: "TikTok" },
  { value: "reels", label: "Instagram Reels" },
  { value: "shorts", label: "YouTube Shorts" },
];

/** Champs du brief d'un projet (étape Idée). */
export default function ProjectFields({
  value,
  onChange,
  projectId,
  locked,
  unsaved,
  foldTheme,
}: {
  value: ProjectIn;
  onChange: (update: (prev: ProjectIn) => ProjectIn) => void;
  /** Contexte de l'assistant IA. */
  projectId: number;
  locked?: boolean;
  /** Brouillon non enregistré (étape Idée) : voir `AssistField`. */
  unsaved?: boolean;
  /** Idée déjà validée : le thème passe dans un volet replié, le titre et le format restent à portée. */
  foldTheme?: boolean;
}) {
  // Mise à jour fonctionnelle : une réponse tardive de l'assistant n'écrase pas les autres champs saisis entre-temps.
  const set = <K extends keyof ProjectIn>(key: K, v: ProjectIn[K]) => onChange((prev) => ({ ...prev, [key]: v }));
  const assist = { context: { projectId }, locked, unsaved };
  const theme = (
    <AssistField label="Thème" kind="theme" value={value.theme} onChange={(v) => set("theme", v)} {...assist}>
      {(f) => (
        <TextArea
          {...f}
          className="input"
          placeholder="Ex. 3 astuces pour mieux dormir, ton direct, public 18-30 ans"
          maxLength={MAX_THEME}
          value={value.theme}
          onChange={(e) => set("theme", e.target.value)}
        />
      )}
    </AssistField>
  );
  return (
    <>
      <AssistField label="Titre" kind="project_title" value={value.title} onChange={(v) => set("title", v)} {...assist}>
        {(f) => (
          <input
            {...f}
            className="input"
            required
            maxLength={200}
            value={value.title}
            onChange={(e) => set("title", e.target.value)}
          />
        )}
      </AssistField>
      {!foldTheme && theme}
      <div className="form-row">
        <Field label="Plateforme">
          <select className="input" value={value.platform} onChange={(e) => set("platform", e.target.value)}>
            {PLATFORMS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Durée cible (s)">
          <input
            className="input"
            type="number"
            min={5}
            max={180}
            required
            value={value.target_duration_s}
            onChange={(e) => set("target_duration_s", e.target.valueAsNumber)}
          />
        </Field>
      </div>
      {foldTheme && <Advanced label="Idée de départ">{theme}</Advanced>}
    </>
  );
}
