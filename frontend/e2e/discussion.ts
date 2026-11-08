import { expect, type Locator, type Page } from "playwright/test";

/** A local port nothing listens on: an agent pointed at it fails at once. */
export const CLOSED_ENDPOINT = "http://127.0.0.1:8099/v1";

/** An agent created in Settings; at an endpoint that never answers, every round fails. */
export async function createAgent(page: Page, name: string, url: string): Promise<void> {
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "AI agents", level: 2 })).toBeVisible();
  await page.getByRole("button", { name: "New agent" }).click();
  await expect(page.getByRole("heading", { name: "New AI agent", level: 1 })).toBeVisible();
  await page.getByLabel("Agent name").fill(name);
  await page.getByLabel("Role template").selectOption({ label: "QA Engineer" });
  await page.getByLabel("API base URL").fill(url);
  await page.getByLabel("Model identifier").fill("offline-model");
  await page.getByLabel("Timeout (seconds)").fill("5");
  await page.getByRole("button", { name: "Save agent" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
}

/** The Ticket's Activity, on the tab whose name matches `tab`; returns the tab's panel. */
export async function activityTab(ticket: Locator, tab: RegExp): Promise<Locator> {
  const activity = ticket.getByRole("region", { name: "Activity" });
  await activity.getByRole("tab", { name: tab }).click();
  const panel = activity.getByRole("tabpanel", { name: tab });
  await expect(panel).toBeVisible();
  return panel;
}

/**
 * Fills the open "Ask the agents" dialog: the agent is chosen to begin with; the other agents
 * the stack holds from other journeys are left out, the question is written, and Ask is pressed.
 * `beforeAsk` runs while the dialog is filled in (an axe check).
 */
export async function askOnly(
  page: Page,
  agentName: string,
  question: string,
  beforeAsk: () => Promise<void> = async () => undefined,
): Promise<void> {
  const ask = page.getByRole("dialog", { name: "Ask the agents" });
  const mine = ask.getByRole("checkbox", { name: `${agentName} QA Engineer` });
  await expect(mine).toBeChecked();
  for (const agent of await ask.getByRole("checkbox").all()) await agent.uncheck();
  await mine.check();
  await ask.getByLabel("Question").fill(question);
  await beforeAsk();
  await ask.getByRole("button", { name: "Ask", exact: true }).click();
}
