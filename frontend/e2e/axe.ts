import { AxeBuilder } from "@axe-core/playwright";
import type { Page, TestInfo } from "playwright/test";

/**
 * The axe-core impacts that fail a journey. Moderate and minor findings do not fail it: each is an
 * annotation on the test, and the full list is attached to the report, so they can be recorded.
 */
const BLOCKING = new Set(["serious", "critical"]);

/**
 * Rules whose findings are design decisions in a theme kit, not regressions. By the product
 * owner's decision of 2026-11-18 only Classic is held to WCAG 2.2 AA contrast; the contrast of the
 * CareNomad and MatchMap palettes is a deliberate choice, so there a color-contrast finding is an
 * annotation like a moderate one. In Classic it fails the journey like any other serious finding.
 */
const DESIGN_FINDINGS: Record<string, ReadonlySet<string>> = {
  carenomad: new Set(["color-contrast"]),
  matchmap: new Set(["color-contrast"]),
  classic: new Set(),
};

/** The theme kit the page shows, as ThemeProvider stamps it on <html>; CareNomad by default. */
async function activeKit(page: Page): Promise<string> {
  return page.evaluate(() => document.documentElement.dataset.themeKit ?? "carenomad");
}

/**
 * Runs axe-core's rules on the page as it is now and returns the serious and critical violations,
 * one line each naming the rule and the elements, so a failure says what to fix. `label` names the
 * attachment when one journey checks several states of a page. Which findings count as design
 * decisions depends on the theme kit the page shows at that moment.
 */
export async function blockingViolations(
  page: Page,
  testInfo: TestInfo,
  label = "axe-violations",
): Promise<string[]> {
  const kit = await activeKit(page);
  // An unknown kit is held to everything, so a new kit cannot slip past the contrast check.
  const designFindings = DESIGN_FINDINGS[kit] ?? new Set<string>();
  const { violations } = await new AxeBuilder({ page }).analyze();
  await testInfo.attach(`${label}.json`, {
    body: JSON.stringify(violations, null, 2),
    contentType: "application/json",
  });
  const blocking = [];
  for (const violation of violations) {
    const impact = violation.impact ?? "unknown";
    const targets = violation.nodes.map((node) => node.target.join(" ")).join(", ");
    const line = `${impact} ${violation.id} [${kit}]: ${violation.help} (${targets})`;
    if (BLOCKING.has(impact) && !designFindings.has(violation.id)) blocking.push(line);
    else testInfo.annotations.push({ type: "axe", description: line });
  }
  return blocking;
}
