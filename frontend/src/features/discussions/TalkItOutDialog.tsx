import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Expander } from "@/components/ui/expander";
import { Field, Input } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { problemAt } from "@/lib/fieldProblems";
import { talkSentence, type TalkRequest } from "./discussionRules";
import { talkProblems, talkRequest, type TalkFields } from "./talkFields";

const DEFAULT_HINT = "Empty means the server's default.";

/** Each field's control, in the order the dialog shows them. */
const CONTROLS: Record<keyof TalkFields, string> = {
  rounds: "talk-rounds",
  tokens: "talk-tokens",
  seconds: "talk-seconds",
};

const ORDER = ["rounds", "tokens", "seconds"] as const;

/**
 * "Let them talk it out": one sentence on what happens, the options behind an expander (the
 * rounds, the rounds left by default; a token and a time budget, empty for the server's
 * defaults) and Start, which sends the run with `autonomous`. Start can always be pressed: a field
 * that is not valid opens the options, says what is wrong under it and takes focus (WCAG 3.3.1);
 * an error follows the field as it is corrected. Mount it with a `key` per opening so the fields
 * start fresh.
 */
export function TalkItOutDialog({
  open,
  rounds,
  pending,
  onClose,
  onStart,
}: {
  open: boolean;
  /** The rounds left, at most four: the default and the most the field takes. */
  rounds: number;
  pending: boolean;
  onClose: () => void;
  onStart: (request: TalkRequest) => void;
}) {
  const [fields, setFields] = useState<TalkFields>({
    rounds: String(rounds),
    tokens: "",
    seconds: "",
  });
  const [optionsOpen, setOptionsOpen] = useState(false);
  const errors = useFieldErrors();
  const set = (field: keyof TalkFields) => (event: { target: { value: string } }) => {
    const next = { ...fields, [field]: event.target.value };
    setFields(next);
    const id = CONTROLS[field];
    if (errors.errorOf(id)) errors.set(id, talkProblems(next, rounds)[field]);
  };
  const numeric = (field: keyof TalkFields) => ({
    id: CONTROLS[field],
    inputMode: "numeric" as const,
    autoComplete: "off",
    value: fields[field],
    onChange: set(field),
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent title="Let them talk it out" description={talkSentence(rounds)}>
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            const problems = talkProblems(fields, rounds);
            const found = ORDER.flatMap((field) => problemAt(CONTROLS[field], problems[field]));
            if (found.length > 0) {
              setOptionsOpen(true);
              errors.report(found);
              return;
            }
            const request = talkRequest(fields, rounds);
            if (request) onStart(request);
          }}
        >
          <Expander title="Options" open={optionsOpen} onToggle={setOptionsOpen}>
            <Field
              label="Rounds"
              htmlFor={CONTROLS.rounds}
              hint={`From 1 to ${String(rounds)}.`}
              error={errors.errorOf(CONTROLS.rounds)}
            >
              <Input {...numeric("rounds")} />
            </Field>
            <Field
              label="Token budget"
              htmlFor={CONTROLS.tokens}
              hint={DEFAULT_HINT}
              error={errors.errorOf(CONTROLS.tokens)}
            >
              <Input {...numeric("tokens")} />
            </Field>
            <Field
              label="Time budget in seconds"
              htmlFor={CONTROLS.seconds}
              hint={DEFAULT_HINT}
              error={errors.errorOf(CONTROLS.seconds)}
            >
              <Input {...numeric("seconds")} />
            </Field>
          </Expander>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <ReasonButton type="submit" disabledReason={pending ? "Starting the run…" : null}>
              Start
            </ReasonButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
