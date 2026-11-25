import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { focusTarget, useFocusAfter } from "./useFocusAfter";

/** The decision whose button goes once it is taken. */
export type Decision = "start" | "complete" | "confirm";

const LINKED_BUTTONS = ["clear-wait", "confirm"] as const;

/**
 * A button of the Ticket a link focuses (`?focus=`), by its `data-focus-target`: `clear-wait` is
 * "Clear the wait", `confirm` is "Confirm human action". The server's decision links
 * (`decision_links.py`) name them.
 */
export type LinkedButton = (typeof LINKED_BUTTONS)[number];

/** The button `?focus=` names; anything else, or nothing, is none. */
export function parseFocus(value: string | null): LinkedButton | null {
  return LINKED_BUTTONS.find((button) => button === value) ?? null;
}

/** The search parameters without `focus`, everything else (`card` over the Kanban) as it was. */
export function withoutFocus(current: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(current);
  next.delete("focus");
  return next;
}

/**
 * Where the focus goes in the Ticket after its decisions (WCAG 2.4.3): Start work becomes Mark
 * complete, so that button takes the focus; Mark complete and a person's confirmation leave no
 * decision, so the title's heading takes it. `focusOnOpen` gives the heading the focus once the
 * Ticket is shown, for a host that swapped the view in under the keyboard (the dialog, back from
 * a discussion). `root` is the view's outer element and `heading` the title's heading.
 *
 * A link to a decision (`?focus=clear-wait`, `?focus=confirm`) focuses its button once the Ticket
 * and what decides its buttons (`settled`: the board and the Loop, which make it read-only) have
 * loaded, on the Ticket's page and in the dialog over the Kanban alike. A button held up by a
 * reason (Confirm while the Ticket waits) takes the focus too, and is read with that reason. Where
 * the button is not there (the wait was cleared, the Ticket confirmed), the heading takes the focus.
 * Only the focus moves: the person presses the button. `focus` then leaves the address, replacing
 * the entry, so the next Ticket opened over the Kanban is not focused by it.
 */
export function useTicketFocus(focusOnOpen: boolean, settled: boolean) {
  const root = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusAfter = useFocusAfter();
  const [params, setParams] = useSearchParams();
  const linked = parseFocus(params.get("focus"));

  useEffect(() => {
    if (focusOnOpen) heading.current?.focus();
  }, [focusOnOpen]);

  useEffect(() => {
    if (linked === null || !settled) return;
    (focusTarget(root.current, linked) ?? heading.current)?.focus();
    setParams(withoutFocus, { replace: true });
  }, [linked, settled, setParams]);

  /** Once the decision's button has gone: the next primary button, else the title. */
  function afterDecision(decision: Decision) {
    focusAfter(() => {
      const view = root.current;
      if (decision === "confirm" && focusTarget(view, "confirm")) return null;
      const primary = view?.querySelector<HTMLElement>("[data-primary-action]");
      if (primary?.dataset.primaryAction === decision) return null;
      return primary ?? heading.current;
    });
  }

  return { root, heading, afterDecision };
}
