import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { FaceCount, FaceDraft, FaceErrors, FaceField } from "./faceLimits";

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
 * The face as fields, for a person: each with its live counter ("14 of 20 words"), a hint for the
 * lists, and the server's messages under the field they name, as the server words them. The
 * server stays the judge; the counters only say where a limit is.
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
  return (
    <form
      aria-label="Edit the face"
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      {FIELDS.map(({ field, label, hint, lines }) => {
        const id = `${base}-${field}`;
        const count = counts[field];
        const messages = errors.fields[field] ?? [];
        const described = `${id}-count`;
        const props = {
          id,
          value: draft[field],
          "aria-describedby": described,
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
            <p
              id={described}
              className="m-0 flex flex-wrap justify-between gap-2 text-xs text-[var(--foreground-faint)]"
            >
              <span>{hint}</span>
              <span
                className={cn("tabular-nums", count.over && "font-medium text-[var(--warning)]")}
              >
                {count.text}
              </span>
            </p>
            {messages.map((message) => (
              <p key={message} role="alert" className="m-0 text-xs text-[var(--destructive)]">
                {message}
              </p>
            ))}
          </div>
        );
      })}
      {errors.other.map((message) => (
        <p key={message} role="alert" className="m-0 text-sm text-[var(--destructive)]">
          {message}
        </p>
      ))}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button variant="quiet" size="sm" disabled={saving} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
