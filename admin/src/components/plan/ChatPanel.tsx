import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, errorMessage, useApi, type PlanMessage } from "../../api";
import { chatBlockedReason, lastUndoable } from "../../planChat";
import TextArea from "../TextArea";

interface Props {
  projectId: number;
  /** Brouillon du plan non enregistré : l'IA n'écrase rien, on demande d'abord d'enregistrer ou d'annuler. */
  dirty: boolean;
  /** Une étape tourne : le serveur refuse (409) de modifier le plan. */
  running: boolean;
  /** Le plan a changé côté serveur (message de l'IA ou annulation) : recharger le projet. */
  onPlanChanged: () => void;
}

/** Conversation avec l'IA sur le plan ; elle répond et, si besoin, modifie le plan (annulable). */
export default function ChatPanel({ projectId, dirty, running, onPlanChanged }: Props) {
  const base = `/projects/${projectId}/plan`;
  const { data: messages, error: loadError, reload } = useApi<PlanMessage[]>(`${base}/messages`);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const log = useRef<HTMLOListElement>(null);
  const blocked = chatBlockedReason({ dirty, running });
  const undoable = messages ? lastUndoable(messages) : null;

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [messages, busy]);

  async function call(path: string, body?: unknown) {
    setBusy(true);
    setError(null);
    try {
      return await api<{ plan_changed?: boolean } | undefined>(`${base}${path}`, {
        method: "POST",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      setError(errorMessage(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const message = text.trim();
    if (!message || blocked || busy) return;
    const done = await call("/chat", { message });
    if (done === null) return; // le message reste dans la zone de saisie pour être renvoyé
    setText("");
    reload();
    if (done?.plan_changed) onPlanChanged();
  }

  async function undo(message: PlanMessage) {
    if ((await call(`/messages/${message.id}/undo`)) === null) return;
    reload();
    onPlanChanged();
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <section className="chat" aria-label="Discuter du plan avec l'IA">
      <h2>Discuter du plan</h2>
      <ol className="chat-log" ref={log} aria-live="polite">
        {messages?.length === 0 && (
          <li className="chat-empty muted">
            Demandez un changement (« raccourcis la scène 2 », « ajoute une scène sur le prix ») ou posez une question
            sur le plan.
          </li>
        )}
        {loadError && <li className="error">{loadError}</li>}
        {messages?.map((m) => (
          <li key={m.id} className={`chat-message chat-${m.role}`}>
            <p>{m.content}</p>
            {m.id === undoable?.id && (
              <span className="chat-changed">
                Plan modifié
                <button type="button" className="btn btn-ghost btn-small" onClick={() => undo(m)} disabled={busy || running}>
                  Annuler
                </button>
              </span>
            )}
          </li>
        ))}
        {busy && <li className="chat-message chat-assistant chat-wait muted">L'IA réfléchit…</li>}
      </ol>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form className="chat-form" onSubmit={send}>
        <TextArea
          className="input"
          rows={2}
          maxLength={2000}
          aria-label="Message pour l'IA"
          placeholder="Que voulez-vous changer ?"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {blocked && <p className="muted chat-blocked">{blocked}</p>}
        <button className="btn" disabled={busy || !text.trim() || blocked !== null}>
          Envoyer
        </button>
      </form>
    </section>
  );
}
