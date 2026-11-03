import { QueryErrorResetBoundary } from "@tanstack/react-query";
import { Component, Suspense, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { isReloadingForStaleChunk } from "./chunkLoading";

/**
 * A layout route that renders the matched child route inside an error boundary. App.tsx places one
 * at each level of the route tree, so every route element is covered by construction: a page that
 * throws while rendering is replaced by a fallback, and the layout around it stays mounted.
 *
 * The boundary sits inside a `QueryErrorResetBoundary`, so "Try again" also resets the queries below
 * it that threw (`throwOnError`): they fetch again instead of throwing their cached error at once.
 * Logging happens at the root, in `reportCaughtError`.
 *
 * Pages are lazy (`lazyPage`), so the boundary also holds the `Suspense` that shows while a page's
 * chunk loads, and catches the import's error if the chunk cannot be loaded.
 */
export function RouteErrorBoundary() {
  const location = useLocation();
  return (
    <QueryErrorResetBoundary>
      {({ reset }) => (
        <ErrorBoundary resetKey={location.key} onReset={reset}>
          <Suspense fallback={<PageLoading />}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      )}
    </QueryErrorResetBoundary>
  );
}

interface ErrorBoundaryProps {
  children: ReactNode;
  /** New on every navigation; a change clears a caught error, as React Router's own boundary does. */
  resetKey: string;
  /** Runs before the children render again. */
  onReset: () => void;
}

type ErrorBoundaryState = { failed: false } | { failed: true; error: unknown };

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { failed: true, error };
  }

  override componentDidUpdate(
    previousProps: ErrorBoundaryProps,
    previousState: ErrorBoundaryState,
  ) {
    // Only an error caught before this navigation is cleared. When the navigation itself led to the
    // throwing page, clearing it now would render that page, and catch its error, a second time.
    if (previousState.failed && previousProps.resetKey !== this.props.resetKey) {
      this.reset();
    }
  }

  private readonly reset = () => {
    this.props.onReset();
    this.setState({ failed: false });
  };

  override render() {
    if (this.state.failed) {
      return <RouteErrorFallback error={this.state.error} onRetry={this.reset} />;
    }
    return this.props.children;
  }
}

function PageLoading() {
  return (
    <div
      role="status"
      className="flex justify-center px-4 py-12 text-sm text-[var(--muted-foreground)]"
    >
      Loading page…
    </div>
  );
}

function reloadPage() {
  window.location.reload();
}

function RouteErrorFallback({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (isReloadingForStaleChunk(error)) {
    // Not an error to report: the page's chunk is gone after an upgrade and the tab is reloading
    // (chunkLoading.ts). No "Try again": React keeps a failed lazy import, so it would fail again.
    return (
      <div className="flex justify-center px-4 py-12">
        <div role="status" className="card-surface flex w-full max-w-md flex-col gap-3 p-6">
          <h1 className="text-lg font-semibold text-[var(--foreground)]">
            Loading the new version
          </h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            Tralala was updated after this page was opened, so the page is reloading.
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={reloadPage}>
              Reload page
            </Button>
          </div>
        </div>
      </div>
    );
  }
  const apiError = error instanceof ApiError ? error : null;
  return (
    <div className="flex justify-center px-4 py-12">
      <div role="alert" className="card-surface flex w-full max-w-md flex-col gap-3 p-6">
        <h1 className="text-lg font-semibold text-[var(--foreground)]">
          This page could not be shown
        </h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          {apiError ? apiError.message : "Something went wrong while showing it."}
        </p>
        {apiError?.requestId ? (
          <p className="text-xs text-[var(--muted-foreground)]">
            Request id: <code className="font-mono select-all">{apiError.requestId}</code>
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button onClick={onRetry}>Try again</Button>
          <Button variant="outline" onClick={reloadPage}>
            Reload page
          </Button>
        </div>
      </div>
    </div>
  );
}
