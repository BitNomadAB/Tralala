import { expect, test, type Locator, type Page } from "playwright/test";
import { addCard, boardWithLoop, login, uniqueName } from "./support";

async function selectTicket(dialog: Locator, title: string): Promise<void> {
  // Every option names the owning Loop, so the visible label is not the bare Ticket title.
  const select = dialog.getByLabel("Ticket", { exact: true });
  const value = await select
    .locator("option")
    .filter({ hasText: title })
    .first()
    .getAttribute("value");
  if (!value) throw new Error(`Ticket ${title} is not selectable`);
  await select.selectOption(value);
}

async function createAgent(page: Page, name: string): Promise<void> {
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "AI agents", level: 2 })).toBeVisible();
  await page.getByRole("button", { name: "New agent" }).click();
  await expect(page.getByRole("heading", { name: "New AI agent", level: 1 })).toBeVisible();
  await page.getByLabel("Agent name").fill(name);
  await page.getByLabel("Role template").selectOption({ label: "QA Engineer" });
  await page.getByLabel("API base URL").fill("http://127.0.0.1:8099/v1");
  await page.getByLabel("Model identifier").fill("offline-model");
  await page.getByLabel("Timeout (seconds)").fill("5");
  await page.getByRole("button", { name: "Save agent" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
}

test.describe("discussion run control", () => {
  test("runs bounded rounds and reports budgets and failures", async ({ page }) => {
    await login(page);
    const boardName = uniqueName("Run board");
    await boardWithLoop(page, boardName);
    await addCard(page, "Todo", "Rate limit review");

    const agentName = uniqueName("Run Agent");
    await createAgent(page, agentName);

    await page.getByRole("link", { name: "Discussions" }).click();
    await expect(page.getByRole("heading", { name: "Discussions", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: `Open discussions for ${boardName}` }).click();
    await expect(page.getByRole("button", { name: "All boards" })).toBeVisible();

    await page.getByRole("button", { name: "New discussion" }).click();
    const createDialog = page.getByRole("dialog", { name: "New discussion" });
    await selectTicket(createDialog, "Rate limit review");
    await createDialog.getByLabel("Goal or question").fill("Should we throttle per actor?");
    await createDialog.getByRole("checkbox", { name: new RegExp(agentName) }).check();
    await createDialog.getByRole("button", { name: "Create discussion" }).click();

    const counter = page.getByTestId("round-counter");
    await expect(counter).toHaveText("Rounds 0");
    // The thread subscribes to its event stream as soon as it is opened.
    await expect(page.getByText("live", { exact: true })).toBeVisible();

    // The agent endpoint is offline, so the round fails fast and is reported, not swallowed.
    await page.getByRole("button", { name: "Run round" }).click();
    await expect(counter).toHaveText(/Rounds 1/, { timeout: 30_000 });
    await expect(page.getByText(/all_participants_failed/).first()).toBeVisible();
    await expect(page.getByText("1 failed")).toBeVisible();

    await page.getByRole("button", { name: "Run autonomously" }).click();
    const runDialog = page.getByRole("dialog", { name: "Run discussion" });
    await expect(runDialog.getByLabel("Rounds")).toHaveValue("3");
    await runDialog.getByLabel("Rounds").fill("2");
    await runDialog.getByLabel("Token budget (optional)").fill("1000");
    await runDialog.getByLabel("Time budget in seconds (optional)").fill("30");
    await runDialog.getByRole("button", { name: "Start run" }).click();

    // A failing run stops instead of retrying the same broken endpoint for every round.
    await expect(counter).toHaveText(/Rounds 2/, { timeout: 30_000 });
    await expect(page.getByText(/all_participants_failed/).first()).toBeVisible();

    const stopButton = page.getByRole("button", { name: "Stop run" });
    await expect(stopButton).toBeDisabled();
    await expect(page.getByRole("button", { name: "Pause run" })).toBeDisabled();

    // A human decision is still possible once the loop is idle.
    await page.getByRole("button", { name: "Approve" }).click();
    const reviewDialog = page.getByRole("dialog", { name: "Approve outcome" });
    await reviewDialog.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByText("Discussion approved")).toBeVisible();

    // A manual thread stays quiet until the message asks for an answer with @agents.
    await page.getByRole("button", { name: "New discussion" }).click();
    const manualDialog = page.getByRole("dialog", { name: "New discussion" });
    await selectTicket(manualDialog, "Rate limit review");
    await manualDialog.getByLabel("Goal or question").fill("Ask the agents explicitly");
    await manualDialog.getByRole("checkbox", { name: new RegExp(agentName) }).check();
    await manualDialog.getByRole("button", { name: "Create discussion" }).click();

    const mentionCounter = page.getByTestId("round-counter");
    await expect(mentionCounter).toHaveText("Rounds 0");
    const replyBox = page.getByLabel("Reply");
    await expect(replyBox).toHaveAttribute("placeholder", /@agents/);
    await replyBox.fill("@agents please answer this message");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(mentionCounter).toHaveText(/Rounds 1/, { timeout: 30_000 });

    // The board with the newest discussion activity is the first entrance in the board list.
    await page.getByRole("button", { name: "All boards" }).click();
    const boardEntries = page
      .getByRole("list", { name: "Boards with discussions" })
      .getByRole("listitem");
    await expect(boardEntries.first()).toContainText(boardName);

    // A thread names its Loop and deep-links the Ticket it is about.
    await page.getByRole("button", { name: `Open discussions for ${boardName}` }).click();
    await page.getByRole("listitem").filter({ hasText: "Rate limit review" }).first().click();
    await expect(page.getByText("in Delivery", { exact: false })).toBeVisible();
    await page.getByRole("link", { name: "Open Rate limit review" }).click();
    await expect(page.getByRole("dialog", { name: "Rate limit review" })).toBeVisible();
    await expect(page).toHaveURL(/\?card=/);
  });
});
