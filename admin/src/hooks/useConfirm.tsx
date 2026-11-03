import { useState } from "react";
import { ConfirmDialog } from "../components/ui";

interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
}

/** Confirmation avant une action destructive ou coûteuse : `confirm(demande)` ouvre la modale, `dialog` est à rendre
 *  dans le composant. L'action ne part qu'une fois confirmée. */
export function useConfirm() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const dialog = request && (
    <ConfirmDialog
      {...request}
      onConfirm={() => {
        setRequest(null);
        request.onConfirm();
      }}
      onCancel={() => setRequest(null)}
    />
  );
  return { confirm: setRequest, dialog };
}
