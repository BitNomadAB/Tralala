import { useEffect, useRef } from "react";
import { focusTarget, useFocusAfter } from "./useFocusAfter";

/** The decision whose button goes once it is taken. */
export type Decision = "start" | "complete" | "confirm";

/**
 * Where the focus goes in the Ticket after its decisions (WCAG 2.4.3): Start work becomes Mark
 * complete, so that button takes the focus; Mark complete and a person's confirmation leave no
 * decision, so the title's heading takes it. `focusOnOpen` gives the heading the focus once the
 * Ticket is shown, for a host that swapped the view in under the keyboard (the dialog, back from
 * a discussion). `root` is the view's outer element and `heading` the title's heading.
 */
export function useTicketFocus(focusOnOpen: boolean) {
  const root = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusAfter = useFocusAfter();

  useEffect(() => {
    if (focusOnOpen) heading.current?.focus();
  }, [focusOnOpen]);

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
