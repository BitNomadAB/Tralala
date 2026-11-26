import { expect, test, type Page } from "playwright/test";
import { mcpAsk, mcpAskError, mcpCall, rowsOf } from "./mcp";
import {
  analysisUnderReview,
  approvedAnalysis,
  approveRoadmap,
  roadmap,
  ticketRow,
} from "./published-plan";
import { ADMIN, boardIdFromUrl, closeDialog, issueToken, login, loopIdFromUrl } from "./support";
import * as plan from "./worker-plan";

/**
 * A link to a person's decision, the address a coding session hands its person (`decision_link`):
 * it survives the sign-in whole, `?dialog=completion` opens the completion dialog, and
 * `?focus=clear-wait` puts the focus on "Clear the wait". The link only opens or focuses; the
 * person presses the button.
 */

const TICKET = "Write the mail";

async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

/** Signs in on the login page a signed-out address was sent to. */
async function signInHere(page: Page): Promise<void> {
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Username").fill(ADMIN.username);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test.describe("a link to a decision", () => {
  test.use({ viewport: { width: 1600, height: 900 } });

  test("opens the completion dialog after the sign-in and focuses Clear the wait", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Decision links");
    const plan = await page.request.post(candidates, { headers, data: roadmap([TICKET]) });
    expect(plan.status()).toBe(201);
    await approveRoadmap(page, TICKET);
    const loopPath = `/boards/${boardIdFromUrl(page)}/loops/${loopIdFromUrl(page)}`;
    const loop = (await (await page.request.get(`/api/v1${loopPath}`)).json()) as {
      data: { key: string };
    };
    const completion = `${loop.data.key} completion and QA`;
    let ticketPath = "";

    await test.step("the Ticket waits for a decision", async () => {
      await ticketRow(page, TICKET).getByRole("button", { name: TICKET, exact: true }).click();
      const dialog = page.getByRole("dialog", { name: TICKET });
      const rail = dialog.getByRole("complementary", { name: "Status and details" });
      await rail.getByRole("button", { name: "Mark as waiting…", exact: true }).click();
      await rail.getByLabel("Why (required)").fill("Which mail service do we use?");
      await rail.getByRole("button", { name: "Save the wait", exact: true }).click();
      await expect(rail.getByRole("button", { name: "Clear the wait", exact: true })).toBeVisible();
      ticketPath =
        (await dialog.getByRole("link", { name: "Open as page" }).getAttribute("href")) ?? "";
      expect(ticketPath).toMatch(/\/tickets\/[0-9a-f-]{36}$/);
      await closeDialog(page);
    });

    await test.step("signed out, the completion link opens its dialog once the person signs in", async () => {
      await signOut(page);
      await page.goto(`${loopPath}?dialog=completion`);
      await signInHere(page);
      const dialog = page.getByRole("dialog", { name: completion, exact: true });
      await expect(dialog).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`${loopPath}\\?dialog=completion$`));
      // The dialog asks; nothing is accepted until the person presses a button.
      await expect(dialog.getByRole("button", { name: "Accept implementation" })).toBeVisible();
    });

    await test.step("closing the dialog takes it out of the address, so a reload does not reopen it", async () => {
      await closeDialog(page);
      await expect(page).toHaveURL(new RegExp(`${loopPath}$`));
      await page.reload();
      await expect(page.getByRole("heading", { name: "Address check", level: 1 })).toBeVisible();
      await expect(page.getByRole("region", { name: /^Column / }).first()).toBeVisible();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    });

    await test.step("the wait's link focuses Clear the wait on the Ticket's page", async () => {
      await page.goto(`${ticketPath}?focus=clear-wait`);
      const clear = page.getByRole("button", { name: "Clear the wait", exact: true });
      await expect(clear).toBeFocused();
      await expect(page).toHaveURL(new RegExp(`${ticketPath}$`));
      await expect(page.getByRole("heading", { name: TICKET, level: 1 })).toBeVisible();
    });

    await test.step("signed out, the wait's link focuses it once the person signs in", async () => {
      await signOut(page);
      await page.goto(`${ticketPath}?focus=clear-wait`);
      await signInHere(page);
      await expect(page.getByRole("heading", { name: TICKET, level: 1 })).toBeVisible();
      await expect(page.getByRole("button", { name: "Clear the wait", exact: true })).toBeFocused();
      // Focused, not pressed: the Ticket still waits.
      const rail = page.getByRole("complementary", { name: "Status and details" });
      await expect(rail.getByText("Which mail service do we use?")).toBeVisible();
    });
  });

  test("a key asks its person to approve the analysis, and learns the outcome", async ({
    page,
    baseURL,
  }) => {
    test.setTimeout(120_000);
    await login(page);
    const { boardId, loopId } = await analysisUnderReview(page, "Ask a person");
    const token = await issueToken(page, plan.WORKER_SCOPES);
    const args = { board_id: boardId, loop_id: loopId, decision: "analysis" };
    const address = `${baseURL}/boards/${boardId}/loops/${loopId}?tab=plan&doc=analysis`;
    let state = "";

    await test.step("a client with the url mode is asked with the decision's address", async () => {
      const asked = await mcpAsk(page, token, "ask_person", args, { elicitation: { url: {} } });
      expect(asked.resultType).toBe("input_required");
      const question = asked.inputRequests?.decision;
      expect(question?.method).toBe("elicitation/create");
      expect(question?.params.mode).toBe("url");
      expect(question?.params.url).toBe(address);
      expect(String(question?.params.message)).toMatch(/^Open Tralala to approve the analysis of /);
      state = asked.requestState ?? "";
      expect(state).not.toBe("");
    });

    await test.step("a client without it gets the same address as text", async () => {
      const text = await mcpAsk(page, token, "ask_person", args);
      expect(text.resultType).toBe("complete");
      expect(text.structuredContent?.status).toBe("waiting_for_person");
      expect(text.structuredContent?.decision_link).toBe(address);
    });

    await test.step("the person opens the address and approves in the browser", async () => {
      await page.goto(address);
      const documents = page
        .getByRole("tabpanel", { name: "Plan" })
        .getByRole("region", { name: "Planning documents" });
      await documents.getByRole("button", { name: "Approve analysis" }).click();
      await expect(documents.getByRole("button", { name: "Approved" })).toBeVisible();
    });

    await test.step("the call repeated with the state answers approved", async () => {
      const options = {
        elicitation: { url: {} },
        inputResponses: { decision: { action: "accept" } },
        requestState: state,
      };
      const decided = await mcpAsk(page, token, "ask_person", args, options);
      expect(decided.resultType).toBe("complete");
      expect(decided.structuredContent).toMatchObject({
        status: "decided",
        decision: "analysis",
        outcome: "approved",
        decided_by: ADMIN.username,
      });
      // The state opened once: repeated again, it is refused and says nothing about the decision.
      const reused = await mcpAskError(page, token, "ask_person", args, options);
      expect(reused.code).toBe(-32602);
      expect(reused.data).toEqual({ reason: "reused" });
    });
  });

  test("a wait a key asked about is cleared, and the Ticket says through which key", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Asked wait");
    const published = await page.request.post(candidates, { headers, data: roadmap([TICKET]) });
    expect(published.status()).toBe(201);
    await approveRoadmap(page, TICKET);
    const boardId = boardIdFromUrl(page);
    const loopId = loopIdFromUrl(page);
    const token = await issueToken(page, plan.WORKER_SCOPES);
    const listed = await mcpCall(page, token, "list_tickets", {
      board_id: boardId,
      loop_id: loopId,
    });
    const ticket = rowsOf<{ id: string; title: string }>(listed, "tickets").find(
      (row) => row.title === TICKET,
    );
    const cardId = ticket?.id ?? "";
    let link = "";

    await test.step("the key sets a wait and asks its person to clear it", async () => {
      await mcpCall(page, token, "set_ticket_wait", {
        board_id: boardId,
        card_id: cardId,
        waiting_for: "decision",
        reason: "Which mail service do we use?",
      });
      const args = { board_id: boardId, loop_id: loopId, decision: "wait", card_id: cardId };
      const asked = await mcpAsk(page, token, "ask_person", args);
      expect(asked.structuredContent?.status).toBe("waiting_for_person");
      link = String(asked.structuredContent?.decision_link);
      expect(link).toMatch(/\/tickets\/[0-9a-f-]{36}\?focus=clear-wait$/);
    });

    await test.step("the person clears it in Tralala", async () => {
      await page.goto(link);
      const clear = page.getByRole("button", { name: "Clear the wait", exact: true });
      await expect(clear).toBeFocused();
      await clear.click();
      await expect(
        page.getByRole("button", { name: "Mark as waiting…", exact: true }),
      ).toBeVisible();
    });

    await test.step("the Ticket shows one comment and the history names the key", async () => {
      await page.reload();
      const comments = page.getByRole("tabpanel", { name: "Comments" });
      const answer = comments.getByText(
        /cleared the wait on this Ticket\. The question came from a coding session through the key worker-key/,
      );
      await expect(answer).toHaveCount(1);
      await page.getByRole("tab", { name: "History" }).click();
      const history = page.getByRole("list", { name: "History" });
      await expect(
        history.getByText(
          /cleared the wait, asked from a coding session through the key worker-key/,
        ),
      ).toBeVisible();
      await expect(
        history.getByText(/asked a person to decide, from a coding session/),
      ).toBeVisible();
    });
  });
});
