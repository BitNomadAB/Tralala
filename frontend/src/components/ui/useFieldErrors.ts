import { useEffect, useState } from "react";
import type { FieldProblem } from "@/lib/fieldProblems";

/**
 * The errors a form shows under its fields, by control id. `report` replaces them all and moves
 * focus to the first problem once it is on screen, so the field is announced together with the
 * error that now describes it; `set` changes one without moving focus, for a check made when
 * leaving a field or a message that goes away while typing.
 */
export function useFieldErrors() {
  const [errors, setErrors] = useState<ReadonlyMap<string, string>>(() => new Map());
  // A new object per report, so reporting the same field twice focuses it twice.
  const [focusTarget, setFocusTarget] = useState<{ id: string } | null>(null);

  useEffect(() => {
    if (focusTarget) document.getElementById(focusTarget.id)?.focus();
  }, [focusTarget]);

  /** Shows these problems in place of the current ones; true when there is at least one. */
  function report(problems: readonly FieldProblem[]): boolean {
    setErrors(new Map(problems.map(({ id, message }) => [id, message])));
    const [first] = problems;
    if (first) setFocusTarget({ id: first.id });
    return first !== undefined;
  }

  /** Shows or clears the error of one control, leaving focus where it is. */
  function set(id: string, message: string | null) {
    setErrors((current) => {
      if ((current.get(id) ?? null) === message) return current;
      const next = new Map(current);
      if (message === null) next.delete(id);
      else next.set(id, message);
      return next;
    });
  }

  return { errorOf: (id: string) => errors.get(id), report, set, hasErrors: errors.size > 0 };
}
