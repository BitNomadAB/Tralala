/** What the list means, in one sentence. */
export const STOPS_RULE =
  "An agent stops and waits for a person only for what this list names; everything else it writes down as a POC decision and goes on.";
export const STOPS_DEFAULT = "This is the default list: no person has written one for this Loop.";
export const STOPS_NONE = "The list is empty: nothing stops an agent.";
export const STOPS_MAX = 12;
export const STOP_MAX_CHARS = 140;

/** The lines a person wrote, one stop a line, empty lines left out. */
export function stopLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}
