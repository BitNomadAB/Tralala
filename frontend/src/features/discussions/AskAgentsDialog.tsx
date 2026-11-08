import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { CheckChip } from "@/components/ui/chip";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { describeError } from "@/lib/describeError";
import { useAskableAgents } from "@/lib/queries";
import { ASK_SENTENCE, askBlocked, NO_ASKABLE_AGENT } from "./inboxRules";
import { useAskAgents } from "./useAskAgents";

const LEGEND = "text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]";

/**
 * "Ask the agents" from a Ticket: the question and the agents as checkable chips with their
 * roles, the board's askable agents, all chosen to begin with. Ask creates the discussion, starts
 * one round and hands its id to `onAsked`, which opens it. A board where no agent can answer says
 * so, with the way to Settings, and Ask stays disabled. Mount it with a `key` per opening so the
 * question and the choice start fresh.
 */
export function AskAgentsDialog({
  open,
  boardId,
  cardId,
  onClose,
  onAsked,
}: {
  open: boolean;
  boardId: string;
  cardId: string;
  onClose: () => void;
  onAsked: (discussionId: string) => void;
}) {
  const questionId = useId();
  const [question, setQuestion] = useState("");
  // The agents left out; every agent is chosen until a person unticks it.
  const [left, setLeft] = useState<ReadonlySet<string>>(new Set());
  const agents = useAskableAgents(boardId, open);
  const ask = useAskAgents(boardId, cardId, onAsked);
  const all = agents.data ?? [];
  const chosen = all.filter((agent) => !left.has(agent.id)).map((agent) => agent.id);
  const blocked = agents.data ? askBlocked(question, chosen.length, all.length) : null;

  function toggle(agentId: string, checked: boolean) {
    const next = new Set(left);
    if (checked) next.delete(agentId);
    else next.add(agentId);
    setLeft(next);
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent title="Ask the agents" description={ASK_SENTENCE}>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (blocked === null && agents.data) {
              ask.mutate({ question, participantIds: chosen });
            }
          }}
        >
          <Field label="Question" htmlFor={questionId}>
            <Textarea
              id={questionId}
              required
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </Field>
          <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
            <legend className={`mb-2 ${LEGEND}`}>Agents</legend>
            {agents.isLoading ? (
              <p className="m-0 text-sm text-[var(--muted-foreground)]">Reading the agents…</p>
            ) : agents.error ? (
              <p role="alert" className="m-0 text-sm text-[var(--destructive)]">
                {describeError(agents.error, "Could not read the agents.")}
              </p>
            ) : all.length === 0 ? (
              <p className="m-0 text-sm text-[var(--muted-foreground)]">
                {NO_ASKABLE_AGENT}{" "}
                <Link to="/settings" className="text-[var(--primary)] underline">
                  Open Settings
                </Link>
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {all.map((agent) => (
                  <CheckChip
                    key={agent.id}
                    checked={!left.has(agent.id)}
                    onChange={(checked) => toggle(agent.id, checked)}
                    label={agent.name}
                    detail={agent.role_template_name ?? undefined}
                  />
                ))}
              </div>
            )}
          </fieldset>
          {ask.error ? (
            <p role="alert" className="m-0 text-sm text-[var(--destructive)]">
              {describeError(ask.error, "Could not ask the agents.")}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={blocked !== null || !agents.data || ask.isPending}
              title={blocked ?? undefined}
            >
              Ask
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
