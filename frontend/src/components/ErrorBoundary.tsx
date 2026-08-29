import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Catches render/lifecycle errors below it so one broken component can't take
 * the whole app down.
 *
 * React unmounts the *entire* root when an error escapes to the top, which is
 * how a single failing chart turned into a blank white page. Wrapping the risky
 * subtrees (anything driving an imperative canvas/WebGL library) keeps the
 * failure local: the rest of the report stays on screen and usable.
 *
 * Note this only catches errors thrown during render, in lifecycle methods, and
 * in constructors below it — not in event handlers, async callbacks, or
 * requestAnimationFrame. Those still need their own try/catch.
 */

interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Replaces the default inline notice. Used by the root boundary, where a
   * full-page message is the right scale of response.
   */
  fallback?: ReactNode;
  /** Names the failing area in the notice and the console warning. */
  label?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the original error and component stack reachable in the console —
    // the boundary swallows it from the UI, not from the developer.
    console.error(
      `[ErrorBoundary${this.props.label ? `: ${this.props.label}` : ""}]`,
      error,
      info.componentStack,
    );
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    return this.props.fallback ?? <InlineErrorFallback label={this.props.label} />;
  }
}

/** Compact notice sized to sit in place of a single panel. */
function InlineErrorFallback({ label }: { label?: string }) {
  return (
    <div
      role="alert"
      className="border border-border bg-bg-off px-4 py-3 font-mono text-sm text-muted"
    >
      {label ? `${label} — ` : ""}Something went wrong.{" "}
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="underline transition-colors hover:text-text"
      >
        Reload
      </button>
    </div>
  );
}

/** Full-page notice for the root boundary, where nothing else is left to show. */
export function RootErrorFallback() {
  return (
    <main
      role="alert"
      className="flex min-h-screen items-center justify-center bg-bg px-6 text-ink"
    >
      <div className="max-w-md text-center">
        <h1 className="font-display text-3xl text-text">Something went wrong.</h1>
        <p className="mt-3 font-sans text-sm text-muted">
          Frame Grader hit an unexpected error. Reloading starts a fresh analysis.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-8 bg-accent px-10 py-4 font-mono text-xs uppercase tracking-widest text-bg transition-colors hover:bg-[#2a2a2a]"
        >
          Reload
        </button>
      </div>
    </main>
  );
}
