import { useMutation } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { HeldButton } from "@/components/ui/held-button";
import { Field, Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { focusTarget, useFocusAfter } from "@/features/cards/useFocusAfter";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { PocAnswer as PocAnswerBody, PocDecision } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { FEEDBACK_FIRST, POC_FEEDBACK_MAX } from "./pocDecisions";
import { pocTicketHref } from "./pocLinks";

/** Told about each answer the server took: the record before it, and as it is now. */
export type PocAnswered = (before: PocDecision, after: PocDecision) => void;

const LINK =
  "rounded text-[var(--primary)] hover:underline focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/** What was answered: OK, or the feedback with the Ticket it became. It takes the focus after. */
function AnswerState({
  boardId,
  loopId,
  item,
}: {
  boardId: string;
  loopId: string;
  item: PocDecision;
}) {
  const who = `${item.answered_by_name ?? "A person"} · ${formatDateTime(item.answered_at)}`;
  if (item.status === "ok") {
    return (
      <p
        tabIndex={-1}
        data-focus-target="poc-answer"
        data-status="ok"
        className="m-0 rounded text-sm focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
      >
        <b className="font-semibold">Answered OK</b>{" "}
        <span className="text-[var(--muted-foreground)]">by {who}</span>
      </p>
    );
  }
  const ticket = item.feedback_ticket;
  return (
    <div
      tabIndex={-1}
      data-focus-target="poc-answer"
      data-status="feedback"
      className="grid gap-1 rounded-md bg-[var(--surface-raised)] p-2.5 text-sm focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
    >
      <p className="m-0">
        <b className="font-semibold">Feedback</b>{" "}
        <span className="text-[var(--muted-foreground)]">by {who}</span>
      </p>
      <p className="m-0 whitespace-pre-wrap [overflow-wrap:anywhere]">{item.feedback}</p>
      {ticket ? (
        <p className="m-0">
          It became Ticket{" "}
          <Link className={LINK} to={pocTicketHref(boardId, loopId, ticket.id)}>
            {ticket.key ?? "the new Ticket"}
          </Link>
          .
        </p>
      ) : null}
    </div>
  );
}

/**
 * The person's answer to one record: "OK" and "Give feedback…" while it is open, "Give feedback…"
 * after an OK, nothing once feedback was given (it is final). Feedback opens a field with "Send
 * feedback" and "Cancel"; the server turns it into a new Ticket. Each answer is announced and the
 * focus goes to the answer now shown; Cancel returns it to "Give feedback…". A refusal (the Loop's
 * stage takes no new Ticket) is shown as the server words it.
 */
export function PocAnswer({
  boardId,
  loopId,
  item,
  canAnswer,
  onAnswered,
}: {
  boardId: string;
  loopId: string;
  item: PocDecision;
  canAnswer: boolean;
  onAnswered: PocAnswered;
}) {
  const announce = useAnnounce();
  const focusAfter = useFocusAfter();
  const root = useRef<HTMLDivElement>(null);
  const fieldId = useId();
  const [writing, setWriting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState<string | null>(null);

  const answer = useMutation({
    mutationFn: (value: PocAnswerBody) => api.answerPocDecision(boardId, loopId, item.id, value),
    onMutate: () => {
      setError(null);
    },
    onSuccess: (updated) => {
      onAnswered(item, updated);
      setWriting(false);
      setFeedback("");
      const key = updated.feedback_ticket?.key;
      announce(
        updated.status === "ok"
          ? `${item.key} answered OK`
          : `Feedback sent on ${item.key}${key ? `; it became Ticket ${key}` : ""}`,
      );
      focusAfter(() =>
        root.current?.querySelector<HTMLElement>(
          `[data-focus-target="poc-answer"][data-status="${updated.status}"]`,
        ),
      );
    },
    onError: (refusal) => {
      setError(describeError(refusal, "The answer was not saved."));
    },
  });

  const trimmed = feedback.trim();
  const open = item.status === "open";
  return (
    <div ref={root} className="grid gap-2">
      {open ? null : <AnswerState boardId={boardId} loopId={loopId} item={item} />}
      {!canAnswer || item.status === "feedback" ? null : writing ? (
        <div className="grid gap-2 rounded-md bg-[var(--surface-raised)] p-2.5">
          <Field
            label="Your feedback"
            htmlFor={fieldId}
            hint={`It becomes a new Ticket in the Loop's first column. At most ${POC_FEEDBACK_MAX} characters.`}
          >
            <Textarea
              id={fieldId}
              autoFocus
              className="min-h-20"
              maxLength={POC_FEEDBACK_MAX}
              value={feedback}
              onChange={(event) => setFeedback(event.target.value)}
            />
          </Field>
          <div className="flex flex-wrap items-start gap-2">
            <ReasonButton
              variant="secondary"
              size="sm"
              disabledReason={!trimmed ? FEEDBACK_FIRST : answer.isPending ? "Sending…" : null}
              onClick={() => answer.mutate({ answer: "feedback", feedback: trimmed })}
            >
              Send feedback
            </ReasonButton>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setWriting(false);
                setError(null);
                focusAfter(() => focusTarget(root.current, "poc-feedback"));
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {open ? (
            <HeldButton
              size="sm"
              variant="secondary"
              data-focus-target="poc-ok"
              held={answer.isPending}
              onClick={() => answer.mutate({ answer: "ok" })}
            >
              OK
            </HeldButton>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            data-focus-target="poc-feedback"
            onClick={() => {
              setError(null);
              setWriting(true);
            }}
          >
            Give feedback…
          </Button>
        </div>
      )}
      {error ? (
        <p role="alert" className="m-0 text-xs text-[var(--destructive)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
