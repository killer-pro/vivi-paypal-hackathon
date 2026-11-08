import { Component, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { ErrorState } from "./ui";
import { t } from "../i18n";

/** Une exception de rendu n'efface plus tout l'écran : message et « Réessayer » à la place de la page. */
class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="center-screen">
        <ErrorState message={t("Cet écran a rencontré une erreur : {error}", { error: this.state.error.message })} onRetry={() => this.setState({ error: null })} />
      </main>
    );
  }
}

/** Remonté à chaque changement de page : naviguer ailleurs remet l'erreur à zéro. */
export default function RouteErrorBoundary({ children }: { children: ReactNode }) {
  return <Boundary key={useLocation().pathname}>{children}</Boundary>;
}
