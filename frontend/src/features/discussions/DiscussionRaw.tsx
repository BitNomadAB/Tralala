import { RawBlock, RawText } from "@/components/ui/raw-text";
import type { Discussion } from "@/lib/types";
import { answersJson, messageHeading, runText } from "./discussionData";

/**
 * "Raw text": what the agents wrote to each other, as it is and unstyled on purpose: the
 * transcript (every message with its author, role, round and time), the answers in the standard
 * as JSON, and the runs with their codes, tokens, time and stop reasons as the API gives them.
 */
export function DiscussionRaw({ discussion }: { discussion: Discussion }) {
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
          <RawText text={runs.map(runText).join("\n\n")} />
        </RawBlock>
      ) : null}
    </div>
  );
}
