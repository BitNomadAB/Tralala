import { CircleAlert } from "lucide-react";
import {
  useId,
  useMemo,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type ReactNode,
  type Ref,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils";
import { FieldContext, useFieldControl } from "./fieldContext";

const base =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  const aria = useFieldControl(props);
  return <input className={cn(base, "h-9", className)} {...props} {...aria} />;
}

export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { ref?: Ref<HTMLTextAreaElement> }) {
  const aria = useFieldControl(props);
  return <textarea className={cn(base, "min-h-24", className)} {...props} {...aria} />;
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  const aria = useFieldControl(props);
  return <select className={cn(base, "h-9 py-0", className)} {...props} {...aria} />;
}

/** A label always names its control: `htmlFor` is required so the association cannot be left out. */
export function Label({
  className,
  htmlFor,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement> & { htmlFor: string }) {
  return (
    <label
      htmlFor={htmlFor}
      className={cn(
        "text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]",
        className,
      )}
      {...props}
    />
  );
}

/**
 * What is wrong with a control, as text under it. The icon and the hidden "Error:" say it is an
 * error to someone who cannot tell it by the colour. A server message often ends without a full
 * stop; it gets one, so a screen reader does not run it into the hint read after it.
 */
export function FieldMessage({ id, children }: { id: string; children: string }) {
  const sentence = /[.!?]$/.test(children.trim()) ? children : `${children.trim()}.`;
  return (
    <p id={id} className="flex items-start gap-1 text-xs text-[var(--destructive)]">
      <CircleAlert aria-hidden="true" size={14} className="mt-px shrink-0" />
      <span>
        <span className="sr-only">Error: </span>
        {sentence}
      </span>
    </p>
  );
}

/**
 * A label, its control, and the control's error and hint. The control whose id is `htmlFor`
 * (an `Input`, `Select` or `Textarea`, or anything that calls `useFieldControl`) is described by
 * the error and the hint and is marked invalid while there is an error, so a screen reader
 * announces both with the field.
 */
export function Field({
  label,
  htmlFor,
  children,
  hint,
  error,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
  hint?: string | undefined;
  /** What is wrong with the value; shown under the control, nothing when empty. */
  error?: string | null | undefined;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const control = useMemo(
    () => ({
      controlId: htmlFor,
      describedBy: [errorId, hintId].filter((part) => part !== undefined).join(" ") || undefined,
      invalid: errorId !== undefined,
    }),
    [htmlFor, errorId, hintId],
  );
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      <FieldContext value={control}>{children}</FieldContext>
      {error && errorId ? <FieldMessage id={errorId}>{error}</FieldMessage> : null}
      {hintId ? (
        <p id={hintId} className="text-xs text-[var(--muted-foreground)]">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
