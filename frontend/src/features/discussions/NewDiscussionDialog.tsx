import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { CheckChip } from "@/components/ui/chip";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { describeError } from "@/lib/describeError";
import { fieldProblems, problemAt } from "@/lib/fieldProblems";
import { useAskableAgents } from "@/lib/queries";
import { NEW_DISCUSSION_SENTENCE, NO_QUESTION, NO_TITLE } from "./boardDiscussionRules";
import { MOST_ASKED } from "./inboxRules";
import { useNewDiscussion } from "./useBoardDiscussions";

const LEGEND = "text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]";

/**
 * "New discussion" on the board: a title and the question, both required, and the board's agents
 * as checkable chips, none chosen to begin with. Without agents the question goes to nobody in
 * particular; with agents one round starts in the background. "Start discussion" with a field left
 * empty says so under it and puts focus there, as does a field the server refuses; afterwards the
 * new discussion opens (`onCreated`). Mount it with a `key` per opening so it starts fresh.
 */
export function NewDiscussionDialog({
  open,
  boardId,
  onClose,
  onCreated,
}: {
  open: boolean;
  boardId: string;
  onClose: () => void;
  onCreated: (discussionId: string) => void;
}) {
  const titleId = useId();
  const questionId = useId();
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const errors = useFieldErrors();
  const agents = useAskableAgents(boardId, open);
  const create = useNewDiscussion(boardId, onCreated);
  const all = agents.data ?? [];
  const participantIds = all.filter((agent) => chosen.has(agent.id)).map((agent) => agent.id);
  const reason = create.isPending
    ? "Starting the discussion…"
    : participantIds.length > MOST_ASKED
      ? `Choose at most ${String(MOST_ASKED)} agents`
      : null;
  // A refusal that names a field shows under it; anything else shows under the form.
  const refused = create.error
    ? fieldProblems(create.error, { title: titleId, goal: questionId })
    : [];

  function toggle(agentId: string, checked: boolean) {
    const next = new Set(chosen);
    if (checked) next.add(agentId);
    else next.delete(agentId);
    setChosen(next);
  }

  function submit() {
    const problems = [
      ...problemAt(titleId, title.trim() === "" ? NO_TITLE : null),
      ...problemAt(questionId, question.trim() === "" ? NO_QUESTION : null),
    ];
    if (errors.report(problems)) return;
    create.mutate(
      { title, question, participantIds },
      {
        onError: (error) =>
          errors.report(fieldProblems(error, { title: titleId, goal: questionId })),
      },
    );
  }

  const clearOnTyping = (id: string, value: string) => {
    if (value.trim() !== "" && errors.errorOf(id)) errors.set(id, null);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent title="New discussion" description={NEW_DISCUSSION_SENTENCE}>
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (reason === null) submit();
          }}
        >
          <Field label="Title" htmlFor={titleId} error={errors.errorOf(titleId)}>
            <Input
              id={titleId}
              required
              maxLength={200}
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                clearOnTyping(titleId, event.target.value);
              }}
            />
          </Field>
          <Field label="Question" htmlFor={questionId} error={errors.errorOf(questionId)}>
            <Textarea
              id={questionId}
              required
              value={question}
              onChange={(event) => {
                setQuestion(event.target.value);
                clearOnTyping(questionId, event.target.value);
              }}
            />
          </Field>
          <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
            <legend className={`mb-2 ${LEGEND}`}>Agents (optional)</legend>
            {agents.isLoading ? (
              <p className="m-0 text-sm text-[var(--muted-foreground)]">Reading the agents…</p>
            ) : agents.error ? (
              <p role="alert" className="m-0 text-sm text-[var(--destructive)]">
                {describeError(agents.error, "Could not read the agents.")}
              </p>
            ) : all.length === 0 ? (
              <p className="m-0 text-sm text-[var(--muted-foreground)]">
                No agent can answer on this board. The question goes to the people on the board.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {all.map((agent) => (
                  <CheckChip
                    key={agent.id}
                    checked={chosen.has(agent.id)}
                    onChange={(checked) => toggle(agent.id, checked)}
                    label={agent.name}
                    detail={agent.role_template_name ?? undefined}
                  />
                ))}
              </div>
            )}
          </fieldset>
          {create.error && refused.length === 0 ? (
            <p role="alert" className="m-0 text-sm text-[var(--destructive)]">
              {describeError(create.error, "Could not start the discussion.")}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <ReasonButton type="submit" disabledReason={reason}>
              Start discussion
            </ReasonButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
