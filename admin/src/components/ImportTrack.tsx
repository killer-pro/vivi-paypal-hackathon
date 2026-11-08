import { useState, type FormEvent } from "react";
import { api, errorMessage, type MusicTrack } from "../api";
import { UploadIcon } from "./icons";
import { Field, FormActions, Modal } from "./ui";
import "./ImportTrack.css";
import { t } from "../i18n";

/** Bouton « Importer une piste » et sa fenêtre (fichier audio, nom, tags) : bibliothèque musicale et étape Musique. */
export default function ImportTrack({
  onImported,
  primary = false,
}: {
  /** Appelé avec la piste créée, fenêtre refermée. */
  onImported: (track: MusicTrack) => void;
  primary?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={primary ? "btn btn-primary" : "btn"} onClick={() => setOpen(true)}>
        <UploadIcon /> {t("Importer une piste")}
      </button>
      {open && (
        <ImportModal
          onClose={() => setOpen(false)}
          onImported={(track) => {
            setOpen(false);
            onImported(track);
          }}
        />
      )}
    </>
  );
}

function ImportModal({ onClose, onImported }: { onClose: () => void; onImported: (track: MusicTrack) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Nom proposé d'après le fichier, tant que l'utilisateur ne l'a pas saisi lui-même.
  const stem = (f: File | null) => f?.name.replace(/\.[^.]+$/, "") ?? "";
  function pick(picked: File | null) {
    if (!name || name === stem(file)) setName(stem(picked));
    setFile(picked);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("name", name.trim());
    body.append("tags", tags);
    setBusy(true);
    setError(null);
    try {
      const track = await api<MusicTrack>("/music", { method: "POST", body });
      onImported(track);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={t("Importer une piste")} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <Field label={t("Fichier audio (50 Mo maximum)")}>
          <input
            className="input file-input"
            type="file"
            accept="audio/*"
            required
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
        </Field>
        <Field label={t("Nom")}>
          <input className="input" required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("Tags, séparés par des virgules")}>
          <input
            className="input"
            placeholder={t("calme, lo-fi, motivation")}
            value={tags}
            onChange={(e) => setTags(e.target.value)}
          />
        </Field>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <FormActions submitLabel={busy ? "Import…" : "Importer"} onCancel={onClose} disabled={busy || !file} primary />
      </form>
    </Modal>
  );
}
