import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/input";

/** Who writes Info, as the field's hint says it: the rule `save_info` and `write_info` apply. */
const INFO_AUTHORS_HINT =
  "A person writes Info. A coding agent may also write it through write_info while the Loop is a draft or its analysis is in review; once planning has started, only a person changes it.";

/** Shown under the disabled editor to a signed-in actor that is not a person. */
const INFO_AGENT_NOTE =
  "This view edits Info for a person. A coding agent writes Info through write_info while the Loop is a draft or its analysis is in review, and a person approves what is planned from it.";

/**
 * The Info tab's editor: each save is a new revision. A person writes Info here; a worker writes it
 * through `write_info` while the Loop is still speculative, which the hint says. `saveGuard`, when
 * given, takes the save button's place: the question asked before a save that would leave a running
 * generation without a result.
 */
export function InfoEditor({
  value,
  onChange,
  isHuman,
  readOnly,
  canSave,
  onSave,
  saveGuard,
}: {
  value: string;
  onChange: (value: string) => void;
  isHuman: boolean;
  readOnly: boolean;
  canSave: boolean;
  onSave: () => void;
  saveGuard?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Field label="Write or revise Info" htmlFor="loop-info" hint={INFO_AUTHORS_HINT}>
        <Textarea
          id="loop-info"
          rows={8}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Requirements, constraints, links and desired outcomes."
          maxLength={200000}
          disabled={readOnly || !isHuman}
        />
      </Field>
      {!isHuman ? <p className="text-[11px] text-[var(--warning)]">{INFO_AGENT_NOTE}</p> : null}
      <div className="flex justify-end">
        {saveGuard ?? (
          <Button disabled={!canSave} onClick={onSave}>
            Save as new revision
          </Button>
        )}
      </div>
    </div>
  );
}
