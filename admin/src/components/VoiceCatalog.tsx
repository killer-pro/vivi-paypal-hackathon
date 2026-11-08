import { useState } from "react";
import { api, errorMessage } from "../api";
import { parseVoices, type Voice } from "../settings";
import { Field } from "./ui";
import { t } from "../i18n";

const VOICE_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** Catalogue de voix des réglages : ajout à la main (nom + identifiant ElevenLabs), import depuis le compte, retrait. */
export default function VoiceCatalog({ value, onChange }: { value: string; onChange: (json: string) => void }) {
  const voices = parseVoices(value);
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = (next: Voice[]) => onChange(JSON.stringify(next));

  // Pas de <form> : le catalogue est dans le formulaire des réglages (les formulaires ne s'imbriquent pas).
  function add() {
    const voiceId = id.trim();
    if (!name.trim() || !VOICE_ID.test(voiceId)) return setError(t("Indiquez un nom et un identifiant (lettres, chiffres, _ et -)."));
    if (voices.some((v) => v.id === voiceId)) return setError(t("Cet identifiant est déjà au catalogue."));
    save([...voices, { id: voiceId, name: name.trim() }]);
    setName("");
    setId("");
    setError(null);
  }

  async function importFromAccount() {
    setImporting(true);
    setError(null);
    try {
      const remote = await api<Voice[]>("/providers/voices");
      const known = new Set(voices.map((v) => v.id));
      save([...voices, ...remote.filter((v) => !known.has(v.id))]);
    } catch (err) {
      setError(errorMessage(err));
    }
    setImporting(false);
  }

  return (
    <div className="voice-catalog">
      <h3>{t("Catalogue de voix")}</h3>
      {voices.length === 0 ? (
        <p className="muted">{t("Aucune voix. Importez celles de votre compte ou ajoutez-en une avec son identifiant.")}</p>
      ) : (
        <ul className="voice-list">
          {voices.map((v) => (
            <li key={v.id}>
              <span>
                {v.name} <small className="muted">{v.id}</small>
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-label={t("Retirer la voix {name}", { name: v.name })}
                onClick={() => save(voices.filter((x) => x.id !== v.id))}
              >
                {t("Retirer")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="voice-add">
        <Field label={t("Nom de la voix")}>
          <input className="input" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("Identifiant ElevenLabs")}>
          <input
            className="input"
            maxLength={64}
            spellCheck={false}
            autoComplete="off"
            value={id}
            onChange={(e) => setId(e.target.value)}
          />
        </Field>
        <button type="button" className="btn" onClick={add}>
          {t("Ajouter")}
        </button>
        <button type="button" className="btn" onClick={importFromAccount} disabled={importing}>
          {importing ? "Import…" : "Importer depuis ElevenLabs"}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <small className="muted">{t("Les changements s'appliquent après « Enregistrer ».")}</small>
    </div>
  );
}
