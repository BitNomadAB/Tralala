import { expect, test, type Page } from "playwright/test";
import { mcpAsk, mcpCall, rowsOf, type AskedResult } from "./mcp";
import { analysisUnderReview, approvedAnalysis, approveRoadmap, roadmap } from "./published-plan";
import { ADMIN, boardIdFromUrl, issueToken, login, loopIdFromUrl, uniqueName } from "./support";
import * as plan from "./worker-plan";

/**
 * Deciding in the editor, the opt-in of `ask_person`: the isolated stack runs with
 * `TRALALA_EDITOR_DECISIONS=true` (scripts/run-playwright.mjs). A person gives a key of their own
 * the right "Decide in the editor" under Settings; that key's `ask_person` is answered as a form,
 * and the answer is the person's decision, marked as taken through that key. A key of the same
 * person without the right, and QA, keep the link.
 */

const TICKET = "Write the mail";
const FORM_AND_URL = { form: {}, url: {} };

/** The answer to a form: the person's choice, as the client sends it back. */
function answering(state: string, decision: string) {
  return {
    elicitation: FORM_AND_URL,
    inputResponses: { decision: { action: "accept", content: { decision } } },
    requestState: state,
  };
}

/** The form a question carries, or a failed step. */
function formOf(asked: AskedResult): Record<string, unknown> {
  expect(asked.resultType).toBe("input_required");
  const question = asked.inputRequests?.decision;
  expect(question?.method).toBe("elicitation/create");
  expect(question?.params.mode).toBe("form");
  expect(asked.requestState ?? "").not.toBe("");
  return question?.params ?? {};
}

/** A key with the right, created under Settings as a person does; returns its token. */
async function keyWithTheRight(page: Page, name: string): Promise<string> {
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("button", { name: "New access key" }).click();
  const dialog = page.getByRole("dialog", { name: "New interaction agent access" });
  await dialog.getByLabel("Agent name").fill(name);
  await expect(dialog.getByLabel("boards:read")).toBeVisible();
  await dialog.getByLabel("loops:read").check();
  const right = dialog.getByRole("checkbox", { name: "Decide in the editor" });
  await expect(right).not.toBeChecked();
  await expect(
    dialog.getByText(
      "Anyone who holds this key can then approve, clear a wait or confirm in your name.",
    ),
  ).toBeVisible();
  await right.check();
  await dialog.getByRole("button", { name: "Create access" }).click();
  const issued = page.getByRole("dialog", { name: "Copy this token now" });
  const token = await issued.getByLabel("New API token").inputValue();
  await issued.getByRole("button", { name: "Done" }).click();
  await issued.getByRole("button", { name: "Close anyway" }).click();
  const row = page.getByRole("listitem").filter({ hasText: name });
  await expect(row.getByText("Decide in the editor", { exact: true })).toBeVisible();
  await expect(row).toContainText("loops:decide");
  return token;
}

test.describe("deciding in the editor", () => {
  test.use({ viewport: { width: 1600, height: 900 } });

  test("a key with the right gets the analysis as a form, and the answer is the person's approval", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await login(page);
    const { boardId, loopId } = await analysisUnderReview(page, "Editor decision");
    const loopPath = `/boards/${boardId}/loops/${loopId}`;
    const keyName = uniqueName("Laptop");
    const token = await keyWithTheRight(page, keyName);
    const plain = await issueToken(page, plan.WORKER_SCOPES);
    const args = { board_id: boardId, loop_id: loopId, decision: "analysis" };
    let state = "";

    await test.step("whoami says both switches are on for the key with the right", async () => {
      const me = await mcpCall(page, token, "whoami");
      expect(me.editor_decisions).toMatchObject({ installation_allows: true, key_has_right: true });
      const other = await mcpCall(page, plain, "whoami");
      expect(other.editor_decisions).toMatchObject({ key_has_right: false });
    });

    await test.step("a key of the same person without the right is offered no form", async () => {
      const asked = await mcpAsk(page, plain, "ask_person", args, { elicitation: FORM_AND_URL });
      expect(asked.inputRequests?.decision?.params.mode).toBe("url");
    });

    await test.step("the key with the right is asked with a form", async () => {
      const asked = await mcpAsk(page, token, "ask_person", args, { elicitation: FORM_AND_URL });
      const form = formOf(asked);
      expect(String(form.message)).toMatch(/^Approve revision 1 of the analysis of .+, or ask/);
      expect(JSON.stringify(form)).not.toContain("http");
      expect(form.requestedSchema).toMatchObject({
        type: "object",
        required: ["decision"],
        properties: {
          decision: {
            oneOf: [
              { const: "approve", title: "Approve" },
              { const: "request_changes", title: "Ask for changes" },
            ],
          },
        },
      });
      state = asked.requestState ?? "";
    });

    await test.step("the answer approve is the person's approval, through the key", async () => {
      const decided = await mcpAsk(page, token, "ask_person", args, answering(state, "approve"));
      expect(decided.resultType).toBe("complete");
      expect(decided.structuredContent).toMatchObject({
        status: "decided",
        outcome: "approved",
        decided_by: ADMIN.username,
        taken_through: keyName,
      });
    });

    await test.step("the analysis is approved and its history names the key", async () => {
      const found = await page.request.get(
        `/api/v1/boards/${boardId}/activity?entity_type=loop&entity_id=${loopId}&action=loop.analysis_reviewed`,
      );
      const rows = (await found.json()) as {
        data: { actor_type: string; changes: Record<string, unknown> }[];
      };
      expect(rows.data).toHaveLength(1);
      expect(rows.data[0]?.actor_type).toBe("user");
      expect(rows.data[0]?.changes.taken_through).toMatchObject({ key_name: keyName, via: "form" });
      await page.goto(`${loopPath}?tab=plan&doc=analysis`);
      const documents = page
        .getByRole("tabpanel", { name: "Plan" })
        .getByRole("region", { name: "Planning documents" });
      await expect(documents.getByRole("button", { name: "Approved" })).toBeVisible();
    });
  });

  test("a wait and the implementation are decided in the editor, QA keeps the link", async ({
    page,
  }) => {
    test.setTimeout(150_000);
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Editor wait");
    const published = await page.request.post(candidates, { headers, data: roadmap([TICKET]) });
    expect(published.status()).toBe(201);
    await approveRoadmap(page, TICKET);
    const boardId = boardIdFromUrl(page);
    const loopId = loopIdFromUrl(page);
    const token = await issueToken(page, [...plan.WORKER_SCOPES, "loops:decide"]);
    const listed = await mcpCall(page, token, "list_tickets", {
      board_id: boardId,
      loop_id: loopId,
    });
    const ticket = rowsOf<{ id: string; title: string }>(listed, "tickets").find(
      (row) => row.title === TICKET,
    );
    const cardId = ticket?.id ?? "";
    const wait = { board_id: boardId, loop_id: loopId, decision: "wait", card_id: cardId };

    await test.step("the key sets a wait and its person clears it in the editor", async () => {
      await mcpCall(page, token, "set_ticket_wait", {
        board_id: boardId,
        card_id: cardId,
        waiting_for: "decision",
        reason: "Which mail service do we use?",
      });
      const asked = await mcpAsk(page, token, "ask_person", wait, { elicitation: FORM_AND_URL });
      formOf(asked);
      const decided = await mcpAsk(
        page,
        token,
        "ask_person",
        wait,
        answering(asked.requestState ?? "", "clear"),
      );
      expect(decided.structuredContent).toMatchObject({ status: "decided", outcome: "cleared" });
    });

    await test.step("the Ticket has exactly one comment and its history names the key", async () => {
      await page.goto(`/boards/${boardId}/loops/${loopId}/tickets/${cardId}`);
      const comments = page.getByRole("tabpanel", { name: "Comments" });
      await expect(
        comments.getByText(/cleared the wait on this Ticket in a coding session through the key/),
      ).toHaveCount(1);
      await page.getByRole("tab", { name: "History" }).click();
      const history = page.getByRole("list", { name: "History" });
      await expect(
        history.getByText(
          /cleared the wait, decided in a coding session through the key worker-key/,
        ),
      ).toBeVisible();
    });

    await test.step("the implementation is accepted in the editor and QA begins", async () => {
      await mcpCall(page, token, "complete_ticket", {
        board_id: boardId,
        card_id: cardId,
        summary: "The mail is written.",
        evidence: ["The unit suite passed"],
      });
      const accept = { board_id: boardId, loop_id: loopId, decision: "implementation" };
      const asked = await mcpAsk(page, token, "ask_person", accept, { elicitation: FORM_AND_URL });
      formOf(asked);
      const decided = await mcpAsk(
        page,
        token,
        "ask_person",
        accept,
        answering(asked.requestState ?? "", "accept"),
      );
      expect(decided.structuredContent).toMatchObject({ status: "decided", outcome: "accepted" });
    });

    await test.step("QA is never offered a form", async () => {
      const qa = { board_id: boardId, loop_id: loopId, decision: "qa" };
      const asked = await mcpAsk(page, token, "ask_person", qa, { elicitation: FORM_AND_URL });
      expect(asked.resultType).toBe("input_required");
      expect(asked.inputRequests?.decision?.params.mode).toBe("url");
      const formOnly = await mcpAsk(page, token, "ask_person", qa, { elicitation: { form: {} } });
      expect(formOnly.structuredContent?.status).toBe("waiting_for_person");
    });
  });
});
