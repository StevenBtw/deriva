import { Component, type ReactNode } from "react";

/** What a view shows while its code is still loading (each page and the editor are chunks of their own). */
export function Loading({ what = "Loading…" }: { what?: string }) {
  return (
    <div className="page pad">
      <span className="muted" role="status">
        {what}
      </span>
    </div>
  );
}

type BoundaryProps = { resetKey: string; children: ReactNode };
type BoundaryState = { error: Error | null; resetKey: string };

/** A chunk that fails to load (a stopped studio, a newer build) shows its error instead of a blank page. */
export class LoadBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<BoundaryState> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  // Another address gets a fresh try, so one failed page does not block the others
  static getDerivedStateFromProps(props: BoundaryProps, state: BoundaryState): Partial<BoundaryState> | null {
    return props.resetKey === state.resetKey ? null : { error: null, resetKey: props.resetKey };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="page">
        <div className="pad error-text" role="alert">
          This page could not be loaded: {this.state.error.message}. Reload the page to try again.
        </div>
      </section>
    );
  }
}
