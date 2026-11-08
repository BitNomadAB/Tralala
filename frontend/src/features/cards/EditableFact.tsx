import { useEffect, useRef, useState, type ReactNode } from "react";
import { Fact } from "@/components/ui/facts";
import { cn } from "@/lib/utils";

/**
 * A fact that is a value until it is clicked, and then its control: `editor` gets `done`, which
 * puts the value back and returns the focus to it. Read-only, it is a plain fact.
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
  editor: (done: () => void) => ReactNode;
  children?: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);

  useEffect(() => {
    if (wasEditing.current && !editing) button.current?.focus();
    wasEditing.current = editing;
  }, [editing]);

  if (readOnly) {
    return (
      <Fact label={label} none={none}>
        {children}
      </Fact>
    );
  }
  if (editing) {
    return <Fact label={label}>{editor(() => setEditing(false))}</Fact>;
  }
  return (
    <Fact label={label}>
      <button
        ref={button}
        type="button"
        aria-label={`${label}: ${valueText}`}
        title={`Change ${label.toLowerCase()}`}
        onClick={() => setEditing(true)}
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
