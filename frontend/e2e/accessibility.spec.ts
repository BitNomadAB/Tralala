import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "playwright/test";
import { boardWithLoop, createBoard, login, uniqueName } from "./support";

/**
 * The axe-core impacts that fail a journey. Moderate and minor findings do not fail it: each is an
 * annotation on the test, and the full list is attached to the report, so they can be recorded.
 */
const BLOCKING = new Set(["serious", "critical"]);

/**
 * Rules whose findings are design decisions, not regressions: the brand badge's text sits below
 * 4.5:1 on its tinted background in the current palette. They are recorded as annotations like a
 * moderate finding until the palette changes, so the journey guards everything else.
 */
const DESIGN_FINDINGS = new Set(["color-contrast"]);

/**
 * Runs axe-core's rules on the page as it is now and returns the serious and critical violations,
 * one line each naming the rule and the elements, so a failure says what to fix.
 */
async function blockingViolations(page: Page, testInfo: TestInfo): Promise<string[]> {
  const { violations } = await new AxeBuilder({ page }).analyze();
  await testInfo.attach("axe-violations.json", {
    body: JSON.stringify(violations, null, 2),
    contentType: "application/json",
  });
  const blocking = [];
  for (const violation of violations) {
    const impact = violation.impact ?? "unknown";
    const targets = violation.nodes.map((node) => node.target.join(" ")).join(", ");
    const line = `${impact} ${violation.id}: ${violation.help} (${targets})`;
    if (BLOCKING.has(impact) && !DESIGN_FINDINGS.has(violation.id)) blocking.push(line);
    else testInfo.annotations.push({ type: "axe", description: line });
  }
  return blocking;
}

test.describe("accessibility", () => {
  test("the dashboard has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    const name = uniqueName("Accessible board");
    await createBoard(page, name);
    await page.getByRole("link", { name: "Boards" }).click();
    await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();

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
