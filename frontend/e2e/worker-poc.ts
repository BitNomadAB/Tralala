import { expect, type Page } from "playwright/test";
import { mcpCall, mcpRefusal, rowsOf } from "./mcp";
import * as plan from "./worker-plan";

/** Where the journey's key works: the board, the Loop and the Ticket it has taken. */
export interface WorkPlace {
  boardId: string;
  loopId: string;
  loopKey: string;
  cardId: string;
}

/**
 * A key meets the three kinds of obstacle over /mcp: it records a POC decision and reports
 * something missing from a person, and neither stops the Ticket; a wait for something the Loop's
 * stop list does not name is refused. The person then finds both records on the Decisions tab, in
 * review order. Leaves the page on the Kanban tab.
 */
export async function obstaclesNeverStop(page: Page, token: string, at: WorkPlace): Promise<void> {
  const decided = await mcpCall(page, token, "record_poc_decision", {
    board_id: at.boardId,
    loop_id: at.loopId,
    card_id: at.cardId,
    title: plan.POC_TITLE,
    chosen: "A warning shows one minute before the session ends.",
    reason: "It is the common practice and costs one line of text.",
    alternative: "No warning at all.",
    change_path: "Change the number of seconds in the settings.",
    builds_on: "The text of the announcement names the minute.",
  });
  expect(decided).toMatchObject({ key: `${at.loopKey}-POC-001`, status: "open", built_on: true });
  const missing = await mcpCall(page, token, "report_missing", {
    board_id: at.boardId,
    loop_id: at.loopId,
    card_id: at.cardId,
    title: plan.MISSING_TITLE,
    missing: "The address the announcement is sent from.",
    reason: "The announcement cannot be sent without a sender.",
    went_around: "The announcement is written and kept unsent.",
    when_provided: "The address is put in the settings and the announcement is sent.",
  });
  expect(missing).toMatchObject({ key: `${at.loopKey}-POC-002`, status: "open" });

  // Neither stopped the Ticket, and a wait for something the stop list does not name is refused.
  const refused = await mcpRefusal(page, token, "set_ticket_wait", {
    board_id: at.boardId,
    card_id: at.cardId,
    waiting_for: "decision",
    reason: "Which colour should the warning have?",
    stop: "The colour of a warning",
  });
  expect(refused.code).toBe("not_a_stop");
  const read = await mcpCall(page, token, "read_ticket", {
    board_id: at.boardId,
    card_id: at.cardId,
  });
  expect(read.allowed_actions).toEqual(expect.arrayContaining(["complete_ticket"]));

  const listed = await mcpCall(page, token, "list_poc_decisions", {
    board_id: at.boardId,
    loop_id: at.loopId,
  });
  expect(rowsOf<{ key: string }>(listed, "items").map((row) => row.key)).toEqual([
    `${at.loopKey}-POC-001`,
    `${at.loopKey}-POC-002`,
  ]);

  await page.reload();
  await page.getByRole("tab", { name: /^Decisions/ }).click();
  await expect(
    page.getByRole("list", { name: "Other work builds on these" }).getByText(plan.POC_TITLE),
  ).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Missing from a person" }).getByText(plan.MISSING_TITLE),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Kanban", exact: true }).click();
}
