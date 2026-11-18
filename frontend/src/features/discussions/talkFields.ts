import { tokensText, type TalkRequest } from "./discussionRules";

/**
 * The fields of "Let them talk it out" as a person types them: what is wrong with each, and the
 * run they ask for once nothing is. Split from `discussionRules.ts`, which holds the words of one
 * discussion.
 */

const WHOLE = /^\d+$/;

/** The largest budgets one run may be given (the server's limits). */
export const MOST_TOKENS = 5_000_000;
export const MOST_SECONDS = 3600;

/** The fields of "Let them talk it out" as typed. */
export interface TalkFields {
  rounds: string;
  tokens: string;
  seconds: string;
}

function budget(value: string, most: number): number | null | undefined {
  const trimmed = value.trim();
  if (trimmed === "") return undefined;
  if (!WHOLE.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return parsed <= most ? parsed : null;
}

/**
 * What is wrong with each field of "Let them talk it out", in the words its error shows, or null
 * where nothing is: the rounds are a whole number from 1 to `most`, a budget is a whole number up
 * to its limit or empty for the server's default.
 */
export function talkProblems(
  fields: TalkFields,
  most: number,
): Record<keyof TalkFields, string | null> {
  const rounds = budget(fields.rounds, most);
  const roundsWrong = rounds === null || rounds === undefined || rounds < 1;
  return {
    rounds: roundsWrong
      ? most === 1
        ? "Use 1: one round is left."
        : `Use a whole number from 1 to ${String(most)}.`
      : null,
    tokens:
      budget(fields.tokens, MOST_TOKENS) === null
        ? `Use a whole number up to ${tokensText(MOST_TOKENS)}, or leave it empty.`
        : null,
    seconds:
      budget(fields.seconds, MOST_SECONDS) === null
        ? `Use a whole number of seconds up to ${String(MOST_SECONDS)}, or leave it empty.`
        : null,
  };
}

/** The dialog's fields as the start call takes them, or null while one of them is not valid. */
export function talkRequest(fields: TalkFields, most: number): TalkRequest | null {
  const rounds = budget(fields.rounds, most);
  const tokens = budget(fields.tokens, MOST_TOKENS);
  const seconds = budget(fields.seconds, MOST_SECONDS);
  if (rounds === null || rounds === undefined || rounds < 1) return null;
  if (tokens === null || seconds === null) return null;
  return {
    autonomous: true,
    rounds,
    ...(tokens === undefined ? {} : { token_budget: tokens }),
    ...(seconds === undefined ? {} : { time_budget_seconds: seconds }),
  };
}
