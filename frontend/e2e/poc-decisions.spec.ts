import { expect, test, type Locator, type Page } from "playwright/test";
import { blockingViolations } from "./axe";
import {
  addCard,
  boardWithLoop,
  csrfToken,
  listRegion,
  login,
  openPlanDocument,
  uniqueName,
} from "./support";

/**
 * POC decisions reviewed the way a person reviews them: three records arrive over REST on a Loop
 * with a Ticket (one other work builds on, one thing missing from a person, one plain decision);
 * the person opens the Decisions tab and reads them in review order under their headings, answers
 * one OK, gives feedback on another and finds the Ticket it became on the Kanban, writes the Loop's
 * stop list under Info and finds it kept after a reload, and sees the dashboard list the Loop while
 * something is missing from a person.
 */

const BUILT_ON = {
  kind: "decision",
  title: "Idle sessions end after 30 minutes",
  chosen: "A session ends after 30 idle minutes.",
  reason: "It matches the limit the bank already uses.",
  alternative: "A limit of 15 minutes.",
  change_path: "Change the limit in the settings and sign everyone out once.",
  builds_on: "The logout page and the audit report count on this limit.",
  details: "Raw notes for the AI about the session store.",
};
const MISSING = {
  kind: "missing",
  title: "The mail service key",
  missing: "An API key for the mail service.",
  reason: "Password reset mails cannot be sent without it.",
  chosen: "Reset mails are written to the log for now.",
  change_path: "Put the key in the settings and turn mails on.",
};
const PLAIN = {
  kind: "decision",
  title: "Dates are shown in the local time zone",
  chosen: "Every date is shown in the reader's own time zone.",
  reason: "People read the times where they are.",
  alternative: "Every date in UTC.",
  change_path: "Switch the date setting to UTC.",
};

async function record(
  page: Page,
  path: string,
  body: Record<string, unknown>,
): Promise<{ key: string }> {
  const response = await page.request.post(`${path}/poc-decisions`, {
    headers: { "X-CSRF-Token": await csrfToken(page) },
    data: body,
  });
  expect(response.status(), await response.text()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data;
}

function decision(panel: Locator, title: string): Locator {
  return panel.getByRole("article", { name: title });
}

test.describe("POC decisions", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("a person reviews, answers and sets the stop list", async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await login(page);
    const loopName = uniqueName("Session limits");
    const { boardId, loopId } = await boardWithLoop(page, uniqueName("POC board"), loopName);
    const api = `/api/v1/boards/${boardId}/loops/${loopId}`;
    const ticket = "Rotate the signing key";
    let builtOnKey = "";

    await test.step("a Loop with a Ticket gets three records over REST", async () => {
      await addCard(page, "Todo", ticket);
      const cards = (await (await page.request.get(`${api}/cards?limit=50`)).json()) as {
        data: { id: string; title: string }[];
      };
      const card = cards.data.find((entry) => entry.title === ticket);
      if (!card) throw new Error("the Ticket was not listed");
      builtOnKey = (await record(page, api, { ...BUILT_ON, card_id: card.id })).key;
      await record(page, api, MISSING);
      await record(page, api, PLAIN);
    });

    const panel = page.getByRole("tabpanel", { name: /^Decisions/ });

    await test.step("the Decisions tab shows them in review order under their headings", async () => {
      await page.reload();
      await expect(page.getByText("1 thing is missing from a person.")).toBeVisible();
      await page.getByRole("tab", { name: "Decisions 3" }).click();
      await expect(page).toHaveURL(/\?tab=decisions/);
      await expect(panel.getByText("3 wait for an answer.")).toBeVisible();
      await expect(panel.getByRole("heading", { level: 3 })).toHaveText([
        "Other work builds on these 1",
        "Missing from a person 1",
        "Other decisions 1",
      ]);
      await expect(panel.getByRole("article").getByRole("heading", { level: 4 })).toHaveText([
        BUILT_ON.title,
        MISSING.title,
        PLAIN.title,
      ]);
      const builtOn = decision(panel, BUILT_ON.title);
      await expect(builtOn.getByRole("link", { name: new RegExp(ticket) })).toBeVisible();
      await expect(builtOn.getByText(BUILT_ON.builds_on)).toBeVisible();
      await builtOn.getByText("Raw text").click();
      await expect(builtOn.getByText(BUILT_ON.details)).toBeVisible();
      expect(await blockingViolations(page, testInfo, "axe-poc-decisions")).toEqual([]);
    });

    await test.step("the person answers one OK", async () => {
      const plain = decision(panel, PLAIN.title);
      await plain.getByRole("button", { name: "OK" }).click();
      await expect(plain.getByText("Answered OK")).toBeVisible();
      await expect(panel.getByText("2 wait for an answer.")).toBeVisible();
    });

    let feedbackKey = "";
    await test.step("feedback on another becomes a Ticket on the Kanban", async () => {
      const builtOn = decision(panel, BUILT_ON.title);
      await builtOn.getByRole("button", { name: "Give feedback…" }).click();
      await builtOn.getByLabel("Your feedback").fill("Use 15 minutes for the admin pages.");
      await builtOn.getByRole("button", { name: "Send feedback" }).click();
      await expect(builtOn.getByText("Use 15 minutes for the admin pages.")).toBeVisible();
      const link = builtOn.getByRole("link", { name: /-UNP-\d+$/ });
      await expect(link).toBeVisible();
      feedbackKey = (await link.textContent()) ?? "";
      expect(feedbackKey).not.toBe("");
      // The new Ticket sits in the Loop's first column, titled after the decision.
      await page.getByRole("tab", { name: "Kanban", exact: true }).click();
      const created = listRegion(page, "Backlog").getByRole("listitem").filter({
        hasText: feedbackKey,
      });
      await expect(created).toContainText(`Feedback on ${builtOnKey}`);
    });

    await test.step("the stop list under Info is kept after a reload", async () => {
      const documents = await openPlanDocument(page, "Info");
      const stops = documents.getByRole("region", { name: "Stops" });
      await expect(stops.getByText("This is the default list", { exact: false })).toBeVisible();
      await stops.getByRole("button", { name: "Edit stops" }).click();
      await stops
        .getByLabel("Stops, one a line")
        .fill("Money\nDeleting data\nA mail to a customer");
      await stops.getByRole("button", { name: "Save stops" }).click();
      await expect(stops.getByRole("button", { name: "Edit stops" })).toBeVisible();
      await page.reload();
      const after = page.getByRole("region", { name: "Stops" });
      await expect(after.getByRole("listitem")).toHaveText([
        "Money",
        "Deleting data",
        "A mail to a customer",
      ]);
      await expect(after.getByText("This is the default list", { exact: false })).toHaveCount(0);
    });

    await test.step("the dashboard lists the Loop while something is missing", async () => {
      await page.goto("/");
      const waits = page.getByRole("list", { name: "Waits for you" });
      await expect(waits.getByText("1 thing is missing from a person.")).toBeVisible();
      await waits.getByRole("link", { name: `Review decisions: ${loopName}` }).click();
      await expect(page).toHaveURL(/\?tab=decisions/);
      await expect(decision(panel, MISSING.title)).toBeVisible();
    });
  });
});
