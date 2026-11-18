import { fieldErrors } from "./describeError";

/** What is wrong with one control: its id and the sentence its Field shows. */
export interface FieldProblem {
  id: string;
  message: string;
}

/**
 * The shortest password the server accepts (`check_password` in the auth service); an operator may
 * configure a longer one, which the server then names when it refuses.
 */
export const MIN_PASSWORD_LENGTH = 8;

/** Why a password someone chooses cannot be used, or null when it can. */
export function passwordProblem(password: string): string | null {
  return password.length < MIN_PASSWORD_LENGTH
    ? `Use at least ${MIN_PASSWORD_LENGTH} characters.`
    : null;
}

/** Why the repeated password is not the one chosen, or null when it is. */
export function confirmationProblem(password: string, confirmation: string): string | null {
  if (confirmation === "") return "Repeat the password.";
  return confirmation === password ? null : "The two passwords do not match.";
}

/** A problem for `id` when `message` is one, else nothing: lists of checks read top to bottom. */
export function problemAt(id: string, message: string | null): FieldProblem[] {
  return message === null ? [] : [{ id, message }];
}

/**
 * The fields an API refusal names, placed on the controls that send them. `controls` maps a
 * request field, as the API spells it, to the id of its control, in the order the form shows them,
 * so the first problem is the first field on screen. A field without a control is left out; the
 * caller says the refusal elsewhere when nothing here matched.
 */
export function fieldProblems(
  error: unknown,
  controls: Readonly<Record<string, string>>,
): FieldProblem[] {
  const named = fieldErrors(error);
  return Object.entries(controls).flatMap(([field, id]) => {
    const found = named.find((entry) => entry.field === field);
    return found ? [{ id, message: found.message }] : [];
  });
}
