import type {
  Discussion,
  DiscussionAnswer,
  DiscussionMessage,
  DiscussionRound,
  DiscussionRun,
  DiscussionStance,
} from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { countText, positionLabel } from "./discussionRules";

/**
 * What the discussion view reads out of the thread the API gives: one row per participant, one
 * line per round, and the Raw text as it is.
 */

export type StanceKind = "answer" | "prose" | "none";

export interface StanceRow {
  id: string;
  name: string;
  role: string | null;
  /** `answer`: in the standard; `prose`: answered, but not in the standard; `none`: no answer. */
  kind: StanceKind;
  stance: DiscussionStance | null;
  answer: DiscussionAnswer | null;
}

/** Each participant in the order they joined, with their latest answer in the standard. */
export function stanceRows(discussion: Discussion): StanceRow[] {
  const stances = discussion.positions ?? [];
  return discussion.participants.map((participant) => {
    const stance = stances.find((entry) => entry.participant_id === participant.participant_id);
    const message = stance
      ? discussion.messages.find((entry) => entry.id === stance.message_id)
      : undefined;
    const answered = discussion.messages.some(
      (entry) =>
        entry.author_type === "agent" && entry.author_actor_id === participant.participant_id,
    );
    const kind: StanceKind = stance
      ? stance.format === "prose"
        ? "prose"
        : "answer"
      : answered
        ? "prose"
        : "none";
    return {
      id: participant.id,
      name: participant.display_name,
      role: participant.role_template_name,
      kind,
      stance: stance ?? null,
      answer: message?.answer ?? null,
    };
  });
}

/** Every round the thread's recent runs hold, oldest first. */
export function allRounds(discussion: Discussion): DiscussionRound[] {
  return (discussion.runs ?? [])
    .flatMap((run) => run.rounds)
    .slice()
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

function byOldest(messages: readonly DiscussionMessage[]): DiscussionMessage[] {
  return messages.slice().sort((a, b) => a.created_at.localeCompare(b.created_at));
}

const QUOTE_LIMIT = 60;

function quote(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > QUOTE_LIMIT ? `${flat.slice(0, QUOTE_LIMIT - 1).trimEnd()}…` : flat;
}

export interface RoundLine {
  id: string;
  number: number;
  text: string;
}

/**
 * One line per round: who asked or replied before it ("You" for the person reading), how many
 * answered, and Tralala's verdict after it. A round no person started is the agents answering
 * each other.
 */
export function roundLines(discussion: Discussion, actorId: string | null): RoundLine[] {
  const people = byOldest(discussion.messages.filter((entry) => entry.author_type !== "agent"));
  const first = people[0];
  let since = "";
  return allRounds(discussion).map((round, index) => {
    const end = round.finished_at || round.created_at;
    const asked = people.filter((entry) => entry.created_at > since && entry.created_at <= end);
    since = end;
    const last = asked.at(-1);
    const who = last ? (last.author_actor_id === actorId ? "You" : last.author_name) : null;
    const opening = !last
      ? "The agents answered each other"
      : last === first
        ? `${who ?? ""} asked the question`
        : `${who ?? ""} replied "${quote(last.content)}"`;
    const answers = round.answers === 0 ? "no answers" : countText(round.answers, "answer");
    const verdict = round.synthesis ? positionLabel(round.synthesis.suggestion.verdict) : null;
    return {
      id: round.id,
      number: round.synthesis?.thread_round ?? index + 1,
      text: [opening, answers, verdict].filter((part) => part !== null).join(" · "),
    };
  });
}

/** A message's heading in the transcript: author, role, round, time. */
export function messageHeading(message: DiscussionMessage): string {
  const parts = [message.author_name, message.author_role ?? message.author_type];
  if (message.round_number > 0) parts.push(`round ${String(message.round_number)}`);
  parts.push(formatDateTime(message.created_at));
  return parts.join(" · ");
}

/** Every answer in the standard as JSON, with who wrote it and in which round. */
export function answersJson(discussion: Discussion): string {
  const answers = discussion.messages.flatMap((message) =>
    message.answer
      ? [{ author: message.author_name, round: message.round_number, ...message.answer }]
      : [],
  );
  return JSON.stringify(answers, null, 2);
}

function elapsed(ms: number): string {
  return ms < 1000 ? `${String(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** A run and its rounds as the API gives them, codes included: the Raw text's run log. */
export function runText(run: DiscussionRun): string {
  const sum = (field: "answers" | "failures" | "repeats") =>
    run.rounds.reduce((total, round) => total + round[field], 0);
  const head = [
    `Run ${run.created_at}`,
    run.status,
    `rounds ${String(run.rounds_completed)} of ${String(run.rounds_requested)}`,
    `answers ${String(sum("answers"))}`,
    `failures ${String(sum("failures"))}`,
    `repeats ${String(sum("repeats"))}`,
    `${String(run.tokens_used)} tokens`,
    elapsed(run.elapsed_ms),
    `stop: ${run.stop_reason ?? "none"}`,
    `started by ${run.started_by_name}`,
  ].join(" · ");
  const rounds = run.rounds.map(
    (round) =>
      `  Round ${String(round.round_number)} · ${round.status} · answers ${String(round.answers)} · failures ${String(round.failures)} · repeats ${String(round.repeats)} · ${String(round.tokens_used)} tokens · ${elapsed(round.elapsed_ms)}`,
  );
  return [head, ...(run.error ? [`  error: ${run.error}`] : []), ...rounds].join("\n");
}
