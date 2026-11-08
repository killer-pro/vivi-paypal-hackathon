import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, errorMessage, useApi, type ProviderModels } from "../api";
import ModelCards from "../components/ModelCards";
import VoiceCatalog from "../components/VoiceCatalog";
import { ErrorState, Field } from "../components/ui";
import { IMAGE_PROVIDER_LABELS, pickable, START_IMAGE_LABELS } from "../models";
import { parseVoices, SECRET_KEYS, settingsBody, voiceLabel, withCurrent, type Settings } from "../settings";
import "./Providers.css";
import { t } from "../i18n";

type Health = Record<string, boolean>;
interface HealthState {
  report?: Health;
  error?: string;
  testing: boolean;
}

/** Champ de réglage : saisie libre, ou liste de choix tirée des modèles disponibles (`/providers/models`). */
interface FieldSpec {
  key: string;
  label: string;
  choices?: (models?: ProviderModels) => string[];
  hint?: string;
}

interface ProviderCard {
  id: string; // clé de `/providers/health`
  name: string;
  role: string;
  fields: FieldSpec[];
}

const PROVIDERS: ProviderCard[] = [
  {
    id: "claude",
    name: "Claude",
    role: t("Idées, scripts et métadonnées"),
    fields: [{ key: "anthropic_api_key", label: t("Clé API Anthropic") }],
  },
  {
    id: "gemini",
    name: "Gemini",
    role: t("Alternative à Claude pour les idées, scripts et métadonnées ; images de référence"),
    fields: [
      { key: "gemini_api_key", label: t("Clé API Google AI Studio") },
      { key: "gemini_model", label: t("Modèle"), choices: (models) => models?.llm.gemini ?? [] },
      {
        key: "gemini_image_model",
        label: t("Modèle d'image"),
        choices: (models) => models?.image.filter((m) => m.provider === "gemini").map((m) => m.id) ?? [],
      },
    ],
  },
  {
    id: "groq",
    name: "Groq",
    role: t("Alternative hébergée pour les idées, scripts et métadonnées, rapide et peu coûteuse"),
    fields: [
      { key: "groq_api_key", label: t("Clé API GroqCloud (gsk_…)") },
      { key: "groq_model", label: t("Modèle"), choices: (models) => models?.llm.groq ?? [] },
    ],
  },
  {
    id: "ollama",
    name: "Ollama",
    role: t("Idées, scripts et métadonnées sur votre machine, sans clé ni coût"),
    fields: [
      { key: "ollama_url", label: t("URL du serveur") },
      { key: "ollama_model", label: t("Modèle (téléchargé avec « ollama pull »)") },
    ],
  },
  {
    id: "fal",
    name: "fal.ai",
    role: t("Clips vidéo et images de référence"),
    fields: [{ key: "fal_key", label: t("Clé API fal.ai") }],
  },
  {
    id: "comfyui",
    name: "ComfyUI",
    role: t("Clips vidéo sur votre serveur"),
    fields: [{ key: "comfyui_url", label: t("URL du serveur") }],
  },
  {
    id: "comfycloud",
    name: "Comfy Cloud",
    role: t("Clips vidéo et images de référence sur les GPU de Comfy Cloud, mêmes profils que ComfyUI (abonnement payant)"),
    fields: [{ key: "comfy_cloud_api_key", label: t("Clé API Comfy Cloud") }],
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    role: t("Voix off"),
    fields: [
      { key: "elevenlabs_api_key", label: t("Clé API ElevenLabs") },
    ],
  },
  {
    id: "langfuse",
    name: "Langfuse",
    role: t("Journal des appels IA (prompts, réponses, coûts)"),
    fields: [
      { key: "langfuse_public_key", label: t("Clé publique (pk-lf-…)") },
      { key: "langfuse_secret_key", label: t("Clé secrète (sk-lf-…)") },
      { key: "langfuse_base_url", label: t("Serveur (vide = cloud.langfuse.com)") },
    ],
  },
];

const LLM_PROVIDER_LABELS: Record<string, string> = { claude: "Claude", gemini: "Gemini", groq: "Groq", ollama: t("Ollama (local)") };

/** Secrets affichés vides : on n'y saisit qu'une nouvelle valeur. */
const draftOf = (saved: Settings): Settings =>
  Object.fromEntries(Object.entries(saved).map(([k, v]) => [k, SECRET_KEYS.has(k) ? "" : v]));

export default function Providers() {
  const settings = useApi<Settings>("/settings");
  const models = useApi<ProviderModels>("/providers/models");
  const [health, setHealth] = useState<HealthState>({ testing: true });
  // Seule la réponse au dernier test compte : un test plus ancien qui répond en retard (ex. avant l'enregistrement
  // de nouvelles clés) ne doit pas écraser le résultat.
  const latestCheck = useRef(0);

  const check = useCallback(() => {
    const request = ++latestCheck.current;
    api<Health>("/providers/health").then(
      (report) => request === latestCheck.current && setHealth({ report, testing: false }),
      (err) => request === latestCheck.current && setHealth({ error: errorMessage(err), testing: false }),
    );
  }, []);
  const retest = () => {
    setHealth((h) => ({ ...h, testing: true }));
    check();
  };
  useEffect(check, [check]);

  return (
    <div className="providers-page">
      <header className="page-head">
        <h1>{t("Réglages")}</h1>
        <div className="page-head-actions">
          <button className="btn" onClick={retest} disabled={health.testing}>
            {health.testing ? t("Test en cours…") : t("Retester")}
          </button>
        </div>
      </header>
      {health.error && <p className="error page-error">{t("Test des connexions impossible.")} {health.error}</p>}
      {models.error && (
        <div className="error page-error" role="alert">
          {t("Liste des modèles indisponible.")} {models.error}{" "}
          <button className="btn btn-small" onClick={models.reload}>
            {t("Réessayer")}
          </button>
        </div>
      )}

      {settings.error && <ErrorState message={settings.error} onRetry={settings.reload} />}
      {!settings.error && !settings.data && <p className="muted">{t("Chargement…")}</p>}
      {settings.data && (
        <SettingsForm initial={settings.data} models={models.data} modelsError={models.error} health={health} onSaved={retest} />
      )}
    </div>
  );
}

function SettingsForm({
  initial,
  models,
  modelsError,
  health,
  onSaved,
}: {
  initial: Settings;
  models?: ProviderModels;
  modelsError?: string | null;
  health: HealthState;
  onSaved: () => void;
}) {
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState(() => draftOf(initial));
  const [status, setStatus] = useState<{ error?: string; done?: boolean }>({});
  const [busy, setBusy] = useState(false);
  const body = settingsBody(saved, draft);
  const dirty = Object.keys(body).length > 0;

  const set = (patch: Settings) => {
    setDraft((d) => ({ ...d, ...patch }));
    setStatus({});
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const next = await api<Settings>("/settings", { method: "PUT", body: JSON.stringify(body) });
      setSaved(next);
      setDraft(draftOf(next));
      setStatus({ done: true });
      onSaved(); // nouvelles clés : on reteste les connexions
    } catch (err) {
      setStatus({ error: errorMessage(err) });
    }
    setBusy(false);
  }

  const input = ({ key, label, choices, hint }: FieldSpec) => {
    if (choices) return select(key, label, withCurrent(choices(models), draft[key] ?? ""));
    const secret = SECRET_KEYS.has(key);
    return (
      <Field key={key} label={label}>
        <input
          className="input"
          type={secret ? "password" : "text"}
          autoComplete="off"
          spellCheck={false}
          placeholder={secret ? saved[key] || t("Non configurée") : undefined}
          value={draft[key] ?? ""}
          onChange={(e) => set({ [key]: e.target.value })}
        />
        {hint && <small className="muted">{hint}</small>}
        {secret && saved[key] && <small className="muted">{t("Laissez vide pour garder la clé enregistrée.")}</small>}
      </Field>
    );
  };

  /** Liste de choix : `options` en valeurs brutes, ou `labels` (valeur → libellé). */
  const select = (
    key: string,
    label: string,
    options: string[],
    labels: Record<string, string> = {},
  ) => (
    <Field key={key} label={label}>
      <select className="input" value={draft[key] ?? ""} onChange={(e) => set({ [key]: e.target.value })}>
        {options.map((value) => (
          <option key={value} value={value}>
            {labels[value] ?? value}
          </option>
        ))}
      </select>
    </Field>
  );

  const voices = parseVoices(draft.voice_catalog);
  const voiceSettings = (
    <>
      {select(
        "default_voice_id",
        t("Voix par défaut"),
        ["", ...withCurrent(voices.map((v) => v.id), draft.default_voice_id ?? "")],
        { "": t("Aucune"), ...Object.fromEntries(voices.map((v) => [v.id, voiceLabel(voices, v.id)])) },
      )}
      <VoiceCatalog value={draft.voice_catalog ?? "[]"} onChange={(json) => set({ voice_catalog: json })} />
    </>
  );

  return (
    <form className="providers" onSubmit={submit}>
      <div className="provider-grid">
        {PROVIDERS.map((p) => (
          <section key={p.id} className={`provider-card st-${healthStatus(health, p.id)}`} aria-labelledby={`pv-${p.id}`}>
            <header className="provider-head">
              <div>
                <h2 id={`pv-${p.id}`}>{p.name}</h2>
                <p className="muted">{p.role}</p>
              </div>
              <HealthBadge health={health} id={p.id} />
            </header>
            {p.fields.map(input)}
            {p.id === "elevenlabs" && voiceSettings}
          </section>
        ))}

        <section className="provider-card provider-defaults" aria-labelledby="pv-defaults">
          <header className="provider-head">
            <div>
              <h2 id="pv-defaults">{t("Choix par défaut")}</h2>
              <p className="muted">{t("Rédaction appliquée aux prochaines étapes, vidéo proposée à l'étape Clips, dépense maximale par vidéo")}</p>
            </div>
          </header>
          <div className="form-row">
            {select(
              "llm_provider",
              t("Rédaction (idées, scripts, métadonnées)"),
              Object.keys(LLM_PROVIDER_LABELS),
              LLM_PROVIDER_LABELS,
            )}
            {select("image_provider", t("Image de référence"), Object.keys(IMAGE_PROVIDER_LABELS), IMAGE_PROVIDER_LABELS)}
          </div>
          <div className="form-row">
            {select("start_image_provider", t("Image de départ des scènes (avancé)"), Object.keys(START_IMAGE_LABELS), START_IMAGE_LABELS)}
          </div>
          <p className="muted">
            {t("Quand une scène a des images de référence, ce générateur les replace dans la scène avant l'animation (ComfyUI et Comfy Cloud seulement). Modifiable à chaque lancement des clips, dans Avancé.")}
          </p>
          <ModelCards
            cards={models?.video}
            error={modelsError}
            // Affiche ce que l'étape Clips proposera réellement (un réglage indisponible ou hérité y est remplacé).
            value={pickable(models?.video ?? [], {
              provider: draft.default_video_provider ?? "",
              model: draft.default_video_model ?? "",
            })}
            onChange={({ provider, model }) => set({ default_video_provider: provider, default_video_model: model })}
            label={t("Profil vidéo proposé à l'étape Clips")}
          />
          <div className="form-row">
            {input({
              key: "project_budget_usd",
              label: t("Budget maximum par vidéo ($)"),
              hint: t("Au-delà, les nouvelles générations payantes sont refusées et le mode automatique s'arrête. 0 = sans limite."),
            })}
          </div>
        </section>
      </div>

      <footer className="providers-foot">
        {status.error && (
          <p className="error" role="alert">
            {status.error}
          </p>
        )}
        {status.done && (
          <p className="muted" role="status">
            {t("Réglages enregistrés.")}
          </p>
        )}
        {dirty && !status.error && <p className="muted">{t("Modifications non enregistrées")}</p>}
        <button className="btn btn-primary" disabled={!dirty || busy}>
          {busy ? t("Enregistrement…") : t("Enregistrer")}
        </button>
      </footer>
    </form>
  );
}

function healthStatus(health: HealthState, id: string): string {
  if (health.testing || !health.report) return "pending";
  return health.report[id] ? "approved" : "failed";
}

/** Pastille de connexion : couleur + libellé (jamais la couleur seule). */
function HealthBadge({ health, id }: { health: HealthState; id: string }) {
  const status = healthStatus(health, id);
  const label = { pending: health.testing ? t("Test…") : t("Inconnu"), approved: t("Connecté"), failed: t("Non connecté") }[status];
  return (
    <span className="status-badge health-badge" role="status">
      <span className="health-dot" aria-hidden />
      {label}
    </span>
  );
}
