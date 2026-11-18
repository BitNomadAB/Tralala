import { useEffect, useRef, useState, type ReactNode } from "react";
import { Fact } from "@/components/ui/facts";
import { cn } from "@/lib/utils";

/**
 * A fact that is a value until it is clicked, and then its control: `editor` gets `done`, which
 * puts the value back and returns the focus to it; `done(false)` leaves the focus where the person
 * moved it (they tabbed out of the control). Read-only, it is a plain fact.
 */
export function EditableFact({
  label,
  valueText,
  none = false,
  readOnly,
  editor,
  children,
}: {
  label: string;
  /** The value in words, for the button's name ("Owner: Ada Member"). */
  valueText: string;
  none?: boolean | undefined;
  readOnly: boolean;
  editor: (done: (returnFocus?: boolean) => void) => ReactNode;
  children?: ReactNode;
}) {
  // Whether the control is shown, and whether closing it gives the focus back to the value.
  const [state, setState] = useState({ editing: false, returnFocus: true });
  const { editing } = state;
  const button = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);

  useEffect(() => {
    if (wasEditing.current && !state.editing && state.returnFocus) button.current?.focus();
    wasEditing.current = state.editing;
  }, [state]);

  if (readOnly) {
    return (
      <Fact label={label} none={none}>
        {children}
      </Fact>
    );
  }
  if (editing) {
    return (
      <Fact label={label}>
        {editor((returnFocus = true) => {
          setState({ editing: false, returnFocus });
        })}
      </Fact>
    );
  }
  return (
    <Fact label={label}>
      <button
        ref={button}
        type="button"
        aria-label={`${label}: ${valueText}`}
        title={`Change ${label.toLowerCase()}`}
        onClick={() => setState({ editing: true, returnFocus: true })}
        className={cn(
          "-mx-1.5 flex min-w-0 flex-wrap items-center gap-2 rounded-md px-1.5 py-0.5 text-left hover:bg-[var(--surface-raised)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]",
          none && "text-[var(--foreground-faint)]",
        )}
      >
        {none ? "None" : children}
      </button>
    </Fact>
  );
}
