import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/input";

/** The Info tab's editor: only a person writes Info, and each save is a new revision. */
export function InfoEditor({
  value,
  onChange,
  isHuman,
  readOnly,
  canSave,
  onSave,
}: {
  value: string;
  onChange: (value: string) => void;
  isHuman: boolean;
  readOnly: boolean;
  canSave: boolean;
  onSave: () => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Field label="Write or revise Info" htmlFor="loop-info">
        <Textarea
          id="loop-info"
          rows={8}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Requirements, constraints, links and desired outcomes. Only a person can edit this."
          maxLength={200000}
          disabled={readOnly || !isHuman}
        />
      </Field>
      {!isHuman ? (
        <p className="text-[11px] text-[var(--warning)]">
          Agents cannot write Info; ask a person to record it.
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button disabled={!canSave} onClick={onSave}>
          Save as new revision
        </Button>
      </div>
    </div>
  );
}
