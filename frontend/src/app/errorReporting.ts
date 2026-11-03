import type { RootOptions } from "react-dom/client";
import { ApiError } from "@/lib/api";
import { isReloadingForStaleChunk } from "./chunkLoading";

/**
 * The root's `onCaughtError` (main.tsx): React calls it once for every error an error boundary
 * caught, so each one reaches the console exactly once. React 19 already logs caught errors by
 * default; a boundary that also logged in `componentDidCatch` would print every error twice.
 *
 * An `ApiError` is not logged: it is the server's answer, logged by the server under the request id
 * the fallback shows. Nor is a page chunk the tab is reloading for after an upgrade
 * (chunkLoading.ts); one that still fails after that reload is logged like any other error.
 */
export const reportCaughtError: NonNullable<RootOptions["onCaughtError"]> = (error, errorInfo) => {
  if (error instanceof ApiError || isReloadingForStaleChunk(error)) return;
  console.error(error, errorInfo.componentStack ?? "");
};
