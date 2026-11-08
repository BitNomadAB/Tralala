import { expect, test } from "playwright/test";
import { blockingViolations } from "./axe";
import { activityTab, askOnly, CLOSED_ENDPOINT, createAgent } from "./discussion";
import {
  addCard,
  boardWithLoop,
  createBoard,
  login,
  openBoardFromDashboard,
  openCard,
  openPlanDocument,
  showTab,
  uniqueName,
} from "./support";

test.describe("accessibility", () => {
  test("the dashboard has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    const name = uniqueName("Accessible board");
    await createBoard(page, name);
    await page.getByRole("link", { name: "Boards" }).click();
    await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: /^Waits for you/, level: 2 })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });

  test("a board page has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    const name = uniqueName("Accessible board");
    await boardWithLoop(page, name);
    await openBoardFromDashboard(page, name);
    await expect(page.getByRole("list", { name: "Current Loops" })).toBeVisible();
    await page.getByText("Agents and repositories").click();
    await page.getByRole("button", { name: "Board actions" }).click();
    await expect(page.getByRole("menu", { name: "Board actions" })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });

  test("a Loop page has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Accessible board"));
    await addCard(page, "Todo", "An accessible card");
    await page.getByRole("button", { name: "Loop actions" }).click();
    await expect(page.getByRole("menu", { name: "Loop actions" })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
    await page.keyboard.press("Escape");
    await openPlanDocument(page, "Info");
    expect(await blockingViolations(page, testInfo, "axe-loop-plan")).toEqual([]);
    await showTab(page, "Notes");
    expect(await blockingViolations(page, testInfo, "axe-loop-notes")).toEqual([]);
  });

  test("a Ticket over the Kanban has no serious or critical axe violations", async ({
    page,
  }, testInfo) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Accessible board"));
    await addCard(page, "Todo", "An accessible Ticket");
    const dialog = await openCard(page, "Todo", "An accessible Ticket");
    await expect(dialog.getByRole("heading", { name: "An accessible Ticket" })).toBeVisible();
    await expect(dialog.getByLabel("Add a note", { exact: true })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
    await dialog.getByRole("tab", { name: "Raw text" }).click();
    expect(await blockingViolations(page, testInfo, "axe-ticket-raw")).toEqual([]);
  });

  test("a discussion over the Kanban and the inbox have no serious or critical axe violations", async ({
    page,
  }, testInfo) => {
    await login(page);
    const { boardId, loopId } = await boardWithLoop(page, uniqueName("Accessible board"));
    await addCard(page, "Todo", "An accessible question");
    const agentName = uniqueName("Accessible Agent");
    await createAgent(page, agentName, CLOSED_ENDPOINT);
    await page.goto(`/boards/${boardId}/loops/${loopId}`);
    const ticket = await openCard(page, "Todo", "An accessible question");
    await activityTab(ticket, /^Discussions/);
    await ticket.getByRole("button", { name: "Ask the agents" }).first().click();
    const question = `Is this readable? ${uniqueName("Q")}`;
    await askOnly(page, agentName, question);
    const thread = page.getByRole("dialog", { name: question });
    await expect(
      thread.getByText(`No answer from ${agentName}: the agent could not be reached.`),
    ).toBeVisible({ timeout: 30_000 });

    expect(await blockingViolations(page, testInfo, "axe-discussion-modal")).toEqual([]);
    await page.goto("/discussions");
    await expect(
      page.getByRole("list", { name: "Waits for your decision" }).getByText(question),
    ).toBeVisible();
    expect(await blockingViolations(page, testInfo, "axe-discussion-inbox")).toEqual([]);
  });

  test("Settings has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Change password" })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });
});
