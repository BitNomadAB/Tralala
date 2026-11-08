import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Expander } from "@/components/ui/expander";
import { Field, Input } from "@/components/ui/input";
import { talkRequest, talkSentence, type TalkRequest } from "./discussionRules";

const DEFAULT_HINT = "Empty means the server's default.";

/**
 * "Let them talk it out": one sentence on what happens, the options behind an expander (the
 * rounds, the rounds left by default; a token and a time budget, empty for the server's
 * defaults) and Start, which sends the run with `autonomous`. Mount it with a `key` per opening so
 * the fields start fresh.
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
  const [fields, setFields] = useState({ rounds: String(rounds), tokens: "", seconds: "" });
  const request = talkRequest(fields, rounds);
  const set = (field: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields({ ...fields, [field]: event.target.value });
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent title="Let them talk it out" description={talkSentence(rounds)}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (request) onStart(request);
          }}
        >
          <Expander title="Options">
            <Field label="Rounds" htmlFor="talk-rounds" hint={`From 1 to ${String(rounds)}.`}>
              <Input
                id="talk-rounds"
                type="number"
                inputMode="numeric"
                min={1}
                max={rounds}
                value={fields.rounds}
                onChange={set("rounds")}
              />
            </Field>
            <Field label="Token budget" htmlFor="talk-tokens" hint={DEFAULT_HINT}>
              <Input
                id="talk-tokens"
                type="number"
                inputMode="numeric"
                min={0}
                value={fields.tokens}
                onChange={set("tokens")}
              />
            </Field>
            <Field label="Time budget in seconds" htmlFor="talk-seconds" hint={DEFAULT_HINT}>
              <Input
                id="talk-seconds"
                type="number"
                inputMode="numeric"
                min={0}
                max={3600}
                value={fields.seconds}
                onChange={set("seconds")}
              />
            </Field>
          </Expander>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={request === null || pending}>
              Start
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
