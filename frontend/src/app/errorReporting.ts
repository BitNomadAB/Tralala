import type { RootOptions } from "react-dom/client";
import { ApiError } from "@/lib/api";

/**
 * The root's `onCaughtError` (main.tsx): React calls it once for every error an error boundary
 * caught, so each one reaches the console exactly once. React 19 already logs caught errors by
 * default; a boundary that also logged in `componentDidCatch` would print every error twice.
 *
 * An `ApiError` is not logged: it is the server's answer, logged by the server under the request id
 * the fallback shows.
 */
export const reportCaughtError: NonNullable<RootOptions["onCaughtError"]> = (error, errorInfo) => {
  if (error instanceof ApiError) return;
  console.error(error, errorInfo.componentStack ?? "");
};
