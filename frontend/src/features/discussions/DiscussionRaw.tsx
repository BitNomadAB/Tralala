import { RawBlock, RawText } from "@/components/ui/raw-text";
import type { Discussion } from "@/lib/types";
import { answersJson, messageHeading, runText } from "./discussionData";
import type { RunFailure } from "./runEvents";

/**
 * "Raw text": what the agents wrote to each other, as it is and unstyled on purpose: the
 * transcript (every message with its author, role, round and time), the answers in the standard
 * as JSON, and every run with its codes, rounds, answers, failures, repeats, tokens, time, stop
 * reason and error as the API gives them, and the agents that failed with their codes.
 */
export function DiscussionRaw({
  discussion,
  failures,
}: {
  discussion: Discussion;
  /** Each run's failed agents with their codes, by run id, from the events. */
  failures: ReadonlyMap<string, readonly RunFailure[]>;
}) {
  const runs = discussion.runs ?? [];
  const answered = discussion.messages.some((message) => message.answer);
  return (
    <div className="grid max-w-[78ch] gap-[18px]">
      <p className="m-0 text-[13px] text-[var(--foreground-faint)]">
        What the agents wrote to each other, as it is. Shown for when you want to dig.
      </p>
      <RawBlock label="Transcript">
        {discussion.messages.length === 0 ? (
          <p className="m-0 text-xs text-[var(--foreground-faint)]">No messages.</p>
        ) : (
          <ol aria-label="Transcript" className="m-0 grid list-none gap-2.5 p-0">
            {discussion.messages.map((message) => (
              <li key={message.id}>
                <RawText text={`${messageHeading(message)}\n${message.content}`} />
              </li>
            ))}
          </ol>
        )}
      </RawBlock>
      {answered ? (
        <RawBlock label="Answers · JSON">
          <RawText text={answersJson(discussion)} />
        </RawBlock>
      ) : null}
      {runs.length > 0 ? (
        <RawBlock label="Runs">
          <RawText
            text={runs
              .map((run, index) => runText(run, runs.length - index, failures.get(run.id)))
              .join("\n\n")}
          />
        </RawBlock>
      ) : null}
    </div>
  );
}
