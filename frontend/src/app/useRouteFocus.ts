import { useEffect, useRef } from "react";
import { NavigationType, useLocation, useNavigationType } from "react-router-dom";

/** How long a page that is still loading may take to show its heading before focus stays put. */
export const HEADING_WAIT_MS = 10_000;

/** An open dialog manages focus itself: it took it on opening and gives it back on closing. */
const DIALOG = '[role="dialog"], [role="alertdialog"]';

/** A field the new page focused itself (an editor's first input has `autoFocus`). */
const TEXT_ENTRY = 'input, textarea, select, [contenteditable="true"], [contenteditable=""]';

/** Focus from a script: an element that is not focusable by itself takes it without a tab stop. */
function focusElement(element: HTMLElement) {
  if (!element.hasAttribute("tabindex")) element.setAttribute("tabindex", "-1");
  element.focus();
}

/** The page's own content: the layout's `<main id="main">`, a bare page's `<main>`, or the body. */
function pageContainer(doc: Document): HTMLElement {
  return doc.getElementById("main") ?? doc.querySelector("main") ?? doc.body;
}

/**
 * Moves focus to the new page's `<h1>` after a navigation (WCAG 2.4.3), so a screen reader starts
 * reading at the page that opened and the next Tab goes on from there, not from the link that was
 * pressed. Focus is left where it is while a dialog is open, and when the page has focused a field
 * of its own. A page that is still loading gets focus on its main region first; its heading takes
 * focus when it appears, unless the person has moved on by then. Returns what stops that wait.
 */
export function focusPageHeading(doc: Document = document): () => void {
  const container = pageContainer(doc);
  const active = doc.activeElement;
  if (doc.querySelector(DIALOG)) return () => undefined;
  if (active && active !== container && container.contains(active) && active.matches(TEXT_ENTRY)) {
    return () => undefined;
  }
  const heading = container.querySelector("h1");
  if (heading) {
    focusElement(heading);
    return () => undefined;
  }
  if (container !== doc.body) focusElement(container);

  // Focus is still the navigation's to move while it sits where the navigation left it.
  const untouched = () => {
    const now = doc.activeElement;
    return now === null || now === doc.body || now === container;
  };
  const observer = new MutationObserver(() => {
    if (doc.querySelector(DIALOG) || !untouched()) {
      stop();
      return;
    }
    const arrived = container.querySelector("h1");
    if (arrived) {
      focusElement(arrived);
      stop();
    }
  });
  const timer = window.setTimeout(() => {
    stop();
  }, HEADING_WAIT_MS);
  function stop() {
    observer.disconnect();
    window.clearTimeout(timer);
  }
  observer.observe(container, { childList: true, subtree: true });
  return stop;
}

/**
 * Calls `focusPageHeading` when the path changes, never for the page the tab opened on: focus
 * moves for a navigation the person made (a click, a key, the browser's back and forward), not
 * for a redirect while the app starts, such as to the login page. A change of the query alone
 * (a Loop's tab, a Ticket opened over the Kanban) is no new page and leaves focus alone.
 */
export function useRouteFocus(): void {
  const { pathname } = useLocation();
  const navigationType = useNavigationType();
  const shown = useRef(pathname);
  const interacted = useRef(false);

  useEffect(() => {
    const mark = () => {
      interacted.current = true;
    };
    document.addEventListener("pointerdown", mark, true);
    document.addEventListener("keydown", mark, true);
    return () => {
      document.removeEventListener("pointerdown", mark, true);
      document.removeEventListener("keydown", mark, true);
    };
  }, []);

  useEffect(() => {
    if (shown.current === pathname) return undefined;
    shown.current = pathname;
    if (!interacted.current && navigationType !== NavigationType.Pop) return undefined;
    return focusPageHeading(document);
  }, [pathname, navigationType]);
}
