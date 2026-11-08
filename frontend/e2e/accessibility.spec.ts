import { expect, test } from "playwright/test";
import { blockingViolations } from "./axe";
import { boardWithLoop, createBoard, login, openBoardFromDashboard, uniqueName } from "./support";

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

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });

  test("Settings has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Change password" })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });
});
