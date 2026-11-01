import { expect, test, type Page } from "playwright/test";
import { addCard, boardWithLoop, login, openCard, uniqueName } from "./support";

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

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

test.describe("agent mentions in ticket comments", () => {
  test("completes a mention, reports the failure and retries without duplicates", async ({
    page,
  }) => {
    await login(page);
    const boardName = uniqueName("Mention board");
    await boardWithLoop(page, boardName);
    await addCard(page, "Todo", "Retry storm");
    const boardUrl = page.url();

    const agentName = uniqueName("Mention Agent");
    await createAgent(page, agentName);

    await page.goto(boardUrl);
    await expect(page.getByRole("heading", { name: "Delivery", level: 1 })).toBeVisible();
    const dialog = await openCard(page, "Todo", "Retry storm");
    await expect(dialog.getByText("live", { exact: true })).toBeVisible();

    const composer = dialog.getByLabel("New comment");
    await composer.click();
    // The filter keeps the autocomplete independent of how many agents the E2E data has by now.
    await composer.fill(`Please @${agentName}`);
    const suggestions = dialog.getByRole("listbox", { name: "Mention an agent" });
    await expect(suggestions).toBeVisible();
    await suggestions.getByRole("option", { name: new RegExp(escapeRegExp(agentName)) }).click();
    await expect(composer).toHaveValue(new RegExp(`^Please @\\[${escapeRegExp(agentName)}\\] $`));
    await composer.fill(`@[${agentName}] can you look at this?`);
    await dialog.getByRole("button", { name: "Send comment" }).click();

    const mentions = dialog.getByRole("list", { name: "Agent mentions" });
    await expect(mentions.getByRole("listitem")).toHaveCount(1);
    await expect(mentions).toContainText(agentName);
    // The agent endpoint is offline, so the job reports a failure instead of hanging.
    await expect(mentions.getByText("failed", { exact: true })).toBeVisible();
    await expect(mentions.getByRole("button", { name: "Retry" })).toBeVisible();

    await mentions.getByRole("button", { name: "Retry" }).click();
    await expect(mentions.getByRole("listitem")).toHaveCount(1);
    await expect(mentions.getByText("failed", { exact: true })).toBeVisible();
    await expect(dialog.getByText(`@[${agentName}] can you look at this?`)).toHaveCount(1);
  });
});
