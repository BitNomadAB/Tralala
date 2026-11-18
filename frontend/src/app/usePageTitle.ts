import { useEffect } from "react";

/** What every title ends with, so a tab among others still says which application it is. */
export const PRODUCT_NAME = "Tralala";

/** Between the parts of a title, most specific first: "Session limits · Payments · Tralala". */
const SEPARATOR = " · ";

/** A name longer than this is cut, so a long discussion question leaves room for the rest. */
const MAX_PART = 80;

/** A name a page shows once its data has loaded: absent while it loads or when it failed. */
type Name = string | null | undefined;

/**
 * What a page's title names, one entry per route of App.tsx. A page that shows one named thing
 * passes its name; until it has loaded, the title names the kind of page instead.
 */
export type TitledPage =
  | { page: "login" }
  | { page: "enrol" }
  | { page: "boards" }
  | { page: "board"; board: Name }
  | { page: "history"; board: Name }
  | { page: "loop"; loop: Name; board: Name }
  | { page: "ticket"; ticketKey: Name; ticket: Name; loop: Name }
  | { page: "discussion"; question: Name }
  | { page: "discussions" }
  | { page: "settings" }
  | { page: "repositories" }
  | { page: "board-template"; isNew: boolean; template: Name }
  | { page: "role-template"; isNew: boolean; role: Name }
  | { page: "agent"; isNew: boolean; agent: Name }
  | { page: "error" };

/** The name as one line, cut to `MAX_PART` characters, or "" when there is none. */
function clean(name: Name): string {
  const line = (name ?? "").replace(/\s+/g, " ").trim();
  return line.length > MAX_PART ? `${line.slice(0, MAX_PART - 1).trimEnd()}…` : line;
}

/** The thing's own name, or what kind of thing it is while the name is not known. */
function named(name: Name, kind: string): string {
  return clean(name) || kind;
}

/** A settings editor: what is being made, or the edited thing's name and its kind. */
function editor(isNew: boolean, newTitle: string, name: Name, kind: string): string[] {
  return isNew ? [newTitle, "Settings"] : [named(name, kind), clean(name) ? kind : ""];
}

function parts(page: TitledPage): string[] {
  switch (page.page) {
    case "login":
      return ["Sign in"];
    case "enrol":
      return ["Choose your password"];
    case "boards":
      return ["Boards"];
    case "board":
      return [named(page.board, "Board")];
    case "history":
      return ["Board history", clean(page.board)];
    case "loop":
      return [named(page.loop, "Loop"), clean(page.board)];
    case "ticket": {
      const ticket = [clean(page.ticketKey), clean(page.ticket)].filter(Boolean).join(" ");
      return [ticket || "Ticket", clean(page.loop)];
    }
    case "discussion":
      return [named(page.question, "Discussion"), clean(page.question) ? "Discussion" : ""];
    case "discussions":
      return ["Discussions"];
    case "settings":
      return ["Settings"];
    case "repositories":
      return ["Repositories", "Settings"];
    case "board-template":
      return editor(page.isNew, "New board template", page.template, "Board template");
    case "role-template":
      return editor(page.isNew, "New role template", page.role, "Role template");
    case "agent":
      return editor(page.isNew, "New AI agent", page.agent, "AI agent");
    case "error":
      return ["Page could not be shown"];
  }
}

/** The document title of a page: what it shows, then where, then the product. */
export function pageTitle(page: TitledPage): string {
  return [...parts(page).filter(Boolean), PRODUCT_NAME].join(SEPARATOR);
}

/**
 * Gives the page its own document title (WCAG 2.4.2), so a tab, the history and a screen reader
 * say which page this is. Each page declared with `lazyPage` in App.tsx calls it once; the next
 * page sets its own, so nothing is restored on unmount.
 */
export function usePageTitle(page: TitledPage): void {
  const title = pageTitle(page);
  useEffect(() => {
    document.title = title;
  }, [title]);
}
