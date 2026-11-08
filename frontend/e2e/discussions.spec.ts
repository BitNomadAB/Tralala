import http from "node:http";
import type { AddressInfo } from "node:net";
import { expect, test } from "playwright/test";
import { blockingViolations } from "./axe";
import { activityTab, askOnly, createAgent } from "./discussion";
import { addCard, boardWithLoop, login, openCard, uniqueName } from "./support";

/** How long the endpoint holds a request before it hangs up, so the first state can be seen. */
const HOLD_MS = 4_000;

/**
 * An endpoint nobody gets an answer from: it takes the connection, holds it for `HOLD_MS` and
 * hangs up without a word (the agent's timeout is longer). A closed port fails before the view
 * can show the agents answering; this one fails the same way a moment later, so the journey
 * sees Stop while a run is under way and the plain words once it has failed.
 */
async function hangUpEndpoint(): Promise<{ url: string; close: () => Promise<void> }> {
  const server = http.createServer((request) => {
    setTimeout(() => request.socket.destroy(), HOLD_MS);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${String(port)}/v1`,
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}

const RUN_TIMEOUT = { timeout: 30_000 };

test.describe("a discussion on a Ticket", () => {
  test.use({ viewport: { width: 1600, height: 900 } });

  let endpoint: Awaited<ReturnType<typeof hangUpEndpoint>> | null = null;
  test.beforeAll(async () => {
    endpoint = await hangUpEndpoint();
  });
  test.afterAll(async () => {
    await endpoint?.close();
  });

  test("a person asks the agents, reads what happened, lets them talk and decides", async ({
    page,
  }, testInfo) => {
    test.setTimeout(180_000);
    await login(page);
    const me = (await (await page.request.get("/api/v1/auth/me")).json()) as {
      data: { name: string };
    };
    const person = me.data.name;
    const { boardId, loopId } = await boardWithLoop(page, uniqueName("Discussion board"));
    const ticket = "Rate limit review";
    await addCard(page, "Todo", ticket);
    const agentName = uniqueName("Offline Agent");
    if (!endpoint) throw new Error("The endpoint did not start");
    await createAgent(page, agentName, endpoint.url);
    const question = `Should we throttle per actor? ${uniqueName("Q")}`;

    const loopPath = `/boards/${boardId}/loops/${loopId}`;
    await page.goto(loopPath);
    await openCard(page, "Todo", ticket);
    const ticketDialog = page.getByRole("dialog", { name: ticket });
    const thread = page.getByRole("dialog", { name: question });
    const sign = thread.getByRole("region", { name: "Tralala's suggestion" });

    await test.step("the Ticket's Discussions tab is empty and offers Ask the agents", async () => {
      const panel = await activityTab(ticketDialog, /^Discussions/);
      await expect(
        panel.getByText("No discussion yet. Ask the agents what they think."),
      ).toBeVisible();
      await expect(
        ticketDialog.getByRole("tab", { name: "Discussions 0", exact: true }),
      ).toBeVisible();
      await panel.getByRole("button", { name: "Ask the agents" }).click();
    });

    await test.step("the dialog preselects the agent; Ask opens the discussion", async () => {
      await askOnly(page, agentName, question, async () => {
        expect(await blockingViolations(page, testInfo, "axe-ask-dialog")).toEqual([]);
      });
      // Whether the first round runs before the discussion opens or after, it ends the same way;
      // the state while the agents answer is checked during Let them talk it out.
      await expect(thread).toBeVisible(RUN_TIMEOUT);
      await expect(page).toHaveURL(/\?card=[^&]+&discussion=/);
    });

    await test.step("the agent cannot be reached: the view says so in plain words", async () => {
      // Every round leaves a suggestion; with no answer it cannot tell and names who is missing.
      await expect(sign).toContainText(`No answer yet from ${agentName}`, RUN_TIMEOUT);
      await expect(sign).toContainText("Unclear");
      await expect(thread.getByRole("region", { name: "Status" })).toContainText(
        "Waits for your decision",
      );
      await expect(thread.getByText("No agent could be reached", { exact: true })).toBeVisible();
      const answers = thread.getByRole("list", { name: "Answers" });
      await expect(
        answers.getByText(`No answer from ${agentName}: the agent could not be reached.`),
      ).toBeVisible();
      const facts = thread.getByRole("region", { name: "Facts" });
      await expect(facts).toContainText("1 of 3");
      // The stop code is for Raw text only.
      await expect(thread.getByRole("tabpanel", { name: "For you" })).not.toContainText(
        "all_participants_failed",
      );
      expect(await blockingViolations(page, testInfo, "axe-discussion-modal")).toEqual([]);

      await thread
        .getByRole("tablist", { name: "View" })
        .getByRole("tab", { name: "Raw text" })
        .click();
      await expect(thread.getByText(/all_participants_failed/).first()).toBeVisible();
      await thread
        .getByRole("tablist", { name: "View" })
        .getByRole("tab", { name: "For you" })
        .click();
    });

    await test.step("Let them talk it out runs the rounds left within a budget", async () => {
      await thread.getByRole("button", { name: "Let them talk it out" }).click();
      const talk = page.getByRole("dialog", { name: "Let them talk it out" });
      await talk.getByText("Options", { exact: true }).click();
      await expect(talk.getByLabel("Rounds")).toHaveValue("2");
      await talk.getByLabel("Rounds").fill("2");
      await talk.getByLabel("Token budget").fill("1000");
      await talk.getByLabel("Time budget in seconds").fill("30");
      await talk.getByRole("button", { name: "Start" }).click();
      await expect(talk).toHaveCount(0);
      // While the agents answer, the sign says where they are and Stop replaces the decision.
      await expect(sign).toContainText("Agents are answering");
      await expect(sign).toContainText("round 2 of 3");
      await expect(thread.getByRole("button", { name: "Stop", exact: true })).toBeVisible();
      await expect(thread.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);

      // A failing run stops instead of retrying the same broken endpoint for every round.
      await expect(thread.getByRole("region", { name: "Facts" })).toContainText(
        "2 of 3",
        RUN_TIMEOUT,
      );
      await expect(thread.getByRole("button", { name: "Stop", exact: true })).toHaveCount(
        0,
        RUN_TIMEOUT,
      );
      await expect(thread.getByText("No agent could be reached", { exact: true })).toBeVisible();
    });

    await test.step("back on the Ticket, the Discussions tab lists the thread", async () => {
      await thread.getByRole("button", { name: "Back to the Ticket" }).click();
      const panel = await activityTab(ticketDialog, /^Discussions/);
      await expect(
        ticketDialog.getByRole("tab", { name: "Discussions 1", exact: true }),
      ).toBeVisible();
      const row = panel
        .getByRole("list", { name: "Discussions" })
        .getByRole("link")
        .filter({ hasText: question });
      await expect(row).toContainText("Waits for your decision");
      await expect(row).toContainText("round 2 of 3");
    });

    await test.step("the inbox and the dashboard list it as waiting for a decision", async () => {
      await page.goto("/discussions");
      await expect(page.getByRole("heading", { name: "Discussions", level: 1 })).toBeVisible();
      await expect(
        page.getByRole("list", { name: "Waits for your decision" }).getByText(question),
      ).toBeVisible();
      expect(await blockingViolations(page, testInfo, "axe-inbox")).toEqual([]);

      await page.goto("/");
      await expect(
        page
          .getByRole("list", { name: "Waits for you" })
          .getByRole("button", { name: `Open discussion: ${question}` }),
      ).toBeVisible();
    });

    await test.step("the discussion as a page; Approve records the decision", async () => {
      await page.goto(loopPath);
      await openCard(page, "Todo", ticket);
      const panel = await activityTab(ticketDialog, /^Discussions/);
      await panel.getByText(question).click();
      await expect(thread).toBeVisible();
      await thread.getByRole("button", { name: "Open as page" }).click();
      await expect(page.getByRole("heading", { name: question, level: 1 })).toBeVisible();
      await expect(page).toHaveURL(/\/tickets\/[^/]+\/discussions\/[^/?]+$/);
      expect(await blockingViolations(page, testInfo, "axe-discussion-page")).toEqual([]);

      await page.getByRole("button", { name: "Approve", exact: true }).click();
      const review = page.getByRole("dialog", { name: "Approve outcome" });
      await review.getByRole("button", { name: "Confirm" }).click();
      await expect(page.getByRole("region", { name: "Status" })).toContainText(
        `Approved by ${person}`,
      );
    });

    await test.step("the decision shows on the Ticket's row and in the inbox's Decided", async () => {
      await page.getByRole("button", { name: "Back to the Ticket" }).click();
      const panel = await activityTab(page.locator("main"), /^Discussions/);
      await expect(panel.getByRole("list", { name: "Discussions" })).toContainText(
        `Approved by ${person}`,
      );
      await page.goto("/discussions");
      const decided = page.getByRole("list", { name: "Decided" });
      await expect(decided.getByRole("link").filter({ hasText: question })).toContainText(
        `Approved by ${person}`,
      );
    });
  });
});
