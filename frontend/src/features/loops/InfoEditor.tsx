import { useId, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { useFocusBack } from "./useFocusBack";

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
 * generation without a result. When the question goes (Back, a choice, or the run ending by itself)
 * a focus it took along comes back to the save button. A person's save button is never `disabled`:
 * saving or with nothing changed it says so beside it and keeps the focus (WCAG 2.4.3).
 */
export function InfoEditor({
  value,
  onChange,
  isHuman,
  readOnly,
  saving,
  changed,
  onSave,
  saveGuard,
}: {
  value: string;
  onChange: (value: string) => void;
  isHuman: boolean;
  readOnly: boolean;
  /** The save is being recorded. */
  saving: boolean;
  /** The person has changed the text since it was last saved. */
  changed: boolean;
  onSave: () => void;
  saveGuard?: ReactNode;
}) {
  const saveId = useId();
  useFocusBack(saveGuard !== undefined && saveGuard !== null, () =>
    document.getElementById(saveId),
  );
  return (
    <div className="flex flex-col gap-2">
      <Field label="Write or revise Info" htmlFor="loop-info" hint={INFO_AUTHORS_HINT}>
        <Textarea
          id="loop-info"
          rows={8}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="The goal: what should be true when this Loop is done. Then requirements, constraints and links."
          maxLength={200000}
          disabled={readOnly || !isHuman}
        />
      </Field>
      {!isHuman ? <p className="text-[11px] text-[var(--warning)]">{INFO_AGENT_NOTE}</p> : null}
      <div className="flex justify-end">
        {saveGuard ??
          (readOnly || !isHuman ? (
            <Button id={saveId} disabled>
              Save as new revision
            </Button>
          ) : (
            <ReasonButton
              id={saveId}
              disabledReason={saving ? "Saving…" : changed ? null : "No changes to save"}
              onClick={onSave}
            >
              Save as new revision
            </ReasonButton>
          ))}
      </div>
    </div>
  );
}
