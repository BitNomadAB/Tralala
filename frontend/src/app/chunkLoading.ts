import { lazy, type ComponentType } from "react";

/**
 * Every page is its own chunk, loaded when a route first renders it. A tab left open across an
 * upgrade still runs the old index.html, so it asks for chunk names the server no longer has. Vite's
 * build wraps each dynamic import in a helper that announces such a failure on `window` as
 * `vite:preloadError` before the import rejects, and Vite's documented answer is to reload the
 * page, which fetches the new index.html and the chunks it names.
 *
 * The reload happens once, never in a loop: a flag in sessionStorage is set before it, a failure
 * while the flag is set is left to the route's error boundary (and logged as any error is), and
 * only a page that loads clears the flag, so the next upgrade can reload the tab again. Layouts are
 * not lazy, so a URL renders one lazy page: after the reload the same page fails first, finds the
 * flag and stops. Without sessionStorage there is no flag, so there is no reload either.
 */

const RELOAD_FLAG = "tralala:stale-chunk-reload";

/** The failed imports a reload was started for. */
const reloadingFor = new WeakSet<object>();

/**
 * Listens for Vite's `vite:preloadError` and reloads once (main.tsx, before the first render).
 * The event is not cancelled: cancelling would resolve the import with `undefined` instead of
 * the page, so React would render that, while the reload is already on its way.
 */
export function watchStaleChunks(
  target: Window = window,
  reload: () => void = () => {
    target.location.reload();
  },
): () => void {
  const onPreloadError = (event: VitePreloadErrorEvent) => {
    if (!claimReload(target)) return;
    reloadingFor.add(event.payload);
    reload();
  };
  target.addEventListener("vite:preloadError", onPreloadError);
  return () => {
    target.removeEventListener("vite:preloadError", onPreloadError);
  };
}

/** True for a failed import the tab is reloading for: shown as "loading", never logged. */
export function isReloadingForStaleChunk(error: unknown): boolean {
  return typeof error === "object" && error !== null && reloadingFor.has(error);
}

/**
 * `React.lazy` for a page that is a named export: `lazyPage(() => import("./X"), "X")`. A page
 * that loads clears the reload flag.
 */
export function lazyPage<Name extends string, Module extends Record<Name, ComponentType>>(
  load: () => Promise<Module>,
  name: Name,
) {
  return lazy(async () => {
    const loaded = await load();
    clearReloadFlag(window);
    return { default: loaded[name] };
  });
}

function claimReload(target: Window): boolean {
  try {
    const storage = target.sessionStorage;
    if (storage.getItem(RELOAD_FLAG) !== null) return false;
    storage.setItem(RELOAD_FLAG, new Date().toISOString());
    return true;
  } catch {
    // Storage blocked or full: without the flag a reload could repeat, so there is none.
    return false;
  }
}

function clearReloadFlag(target: Window) {
  try {
    target.sessionStorage.removeItem(RELOAD_FLAG);
  } catch {
    // Storage blocked: no flag could have been set either.
  }
}
