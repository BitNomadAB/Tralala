import { useEffect, useId } from "react";
import { FieldMessage, Input, Label, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { FaceCount, FaceDraft, FaceErrors, FaceField } from "./faceLimits";
import { PendingButton } from "./PendingButton";

/** The fields in the order the face reads: the summary, the steps, then the three expanders. */
const FIELDS: readonly { field: FaceField; label: string; hint?: string; lines?: boolean }[] = [
  { field: "summary", label: "Summary" },
  { field: "steps", label: "What will be done", hint: "One step per line.", lines: true },
  { field: "why", label: "Why it is needed" },
  { field: "if_skipped", label: "If we skip it" },
  { field: "pros", label: "For", hint: "One point per line.", lines: true },
  { field: "cons", label: "Against", hint: "One point per line.", lines: true },
];

/**
 * The face as fields, for a person: each with its live counter ("14 of 20 words", and what is
 * needed when a field is outside its limits), a hint for the lists, and the server's messages under
 * the field they name, as the server words them. Each field is described by its messages and its
 * counter, and a refused save puts the focus on the first field with a message, so a screen reader
 * reads the field with what is wrong with it. The server stays the judge; the counters only say
 * where a limit is. The first field takes the focus when the form opens.
 */
export function TicketFaceEdit({
  draft,
  counts,
  errors,
  saving,
  onChange,
  onSave,
  onCancel,
}: {
  draft: FaceDraft;
  counts: Record<FaceField, FaceCount>;
  errors: FaceErrors;
  saving: boolean;
  onChange: (field: FaceField, value: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const base = useId();

  // A new refusal (a new errors object) sends the focus to the first field it names.
  useEffect(() => {
    const first = FIELDS.find(({ field }) => (errors.fields[field] ?? []).length > 0);
    if (first) document.getElementById(`${base}-${first.field}`)?.focus();
  }, [errors, base]);

  return (
    <form
      aria-label="Edit the face"
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      {FIELDS.map(({ field, label, hint, lines }, index) => {
        const id = `${base}-${field}`;
        const count = counts[field];
        const messages = errors.fields[field] ?? [];
        const messageIds = messages.map((_message, place) => `${id}-error-${String(place)}`);
        const counter = `${id}-count`;
        const props = {
          id,
          value: draft[field],
          autoFocus: index === 0,
          "aria-describedby": [...messageIds, counter].join(" "),
          "aria-invalid": messages.length > 0 || undefined,
          onChange: (event: { target: { value: string } }) => {
            onChange(field, event.target.value);
          },
        };
        return (
          <div key={field} className="grid gap-1.5">
            <Label htmlFor={id}>{label}</Label>
            {field === "summary" ? (
              <Input {...props} />
            ) : (
              <Textarea {...props} className={lines ? "min-h-24" : "min-h-16"} />
            )}
            {messages.map((message, place) => (
              <FieldMessage key={message} id={messageIds[place] ?? `${id}-error`}>
                {message}
              </FieldMessage>
            ))}
            <p
              id={counter}
              className="m-0 flex flex-wrap justify-between gap-2 text-xs text-[var(--foreground-faint)]"
            >
              <span>{hint}</span>
              <span
                className={cn("tabular-nums", count.over && "font-medium text-[var(--warning)]")}
              >
                {count.text}
              </span>
            </p>
          </div>
        );
      })}
      {errors.other.map((message) => (
        <p key={message} role="alert" className="m-0 text-sm text-[var(--destructive)]">
          {message}
        </p>
      ))}
      <div className="flex gap-2">
        <PendingButton type="submit" size="sm" pending={saving}>
          {saving ? "Saving…" : "Save"}
        </PendingButton>
        <PendingButton variant="quiet" size="sm" pending={saving} onClick={onCancel}>
          Cancel
        </PendingButton>
      </div>
    </form>
  );
}
