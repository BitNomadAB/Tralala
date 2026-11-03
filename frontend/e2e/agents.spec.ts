import { expect, test, type Page } from "playwright/test";
import { login, uniqueName } from "./support";

function roleRow(page: Page, name: string) {
  return page.getByRole("listitem").filter({ has: page.getByText(name, { exact: true }) });
}

function agentRow(page: Page, name: string) {
  return page.getByRole("listitem").filter({ has: page.getByText(name, { exact: true }) });
}

async function openSettings(page: Page) {
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Role templates", level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI agents", level: 2 })).toBeVisible();
}

test.describe("role templates and agents", () => {
  test("customizes and restores a built-in role template", async ({ page }) => {
    await login(page);
    await openSettings(page);

    await roleRow(page, "Lead Developer")
      .getByRole("button", { name: "Edit Lead Developer" })
      .click();
    await expect(
      page.getByRole("heading", { name: /Edit Lead Developer/, level: 1 }),
    ).toBeVisible();
    await expect(page.getByLabel("System prompt")).toHaveValue(/Lead Developer/);
    await page.getByLabel("System prompt").fill("You are a very terse lead developer.");
    await page.getByRole("button", { name: "Save role" }).click();

    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
    await expect(roleRow(page, "Lead Developer")).toContainText("customized");

    await roleRow(page, "Lead Developer")
      .getByRole("button", { name: "Edit Lead Developer" })
      .click();
    await page.getByRole("button", { name: "Restore factory prompt" }).click();
    await expect(page.getByLabel("System prompt")).toHaveValue(/Lead Developer/);
    await page.getByRole("button", { name: "Save role" }).click();
    await expect(roleRow(page, "Lead Developer")).not.toContainText("customized");
  });

  test("duplicates a role template and deletes the custom copy", async ({ page }) => {
    await login(page);
    await openSettings(page);

    const source = uniqueName("Dup Source");
    await page.getByRole("button", { name: "New role" }).click();
    await page.getByLabel("Name").fill(source);
    await page.getByLabel("System prompt").fill("Source prompt for duplication.");
    await page.getByRole("button", { name: "Save role" }).click();
    await expect(roleRow(page, source)).toBeVisible();

    await roleRow(page, source)
      .getByRole("button", { name: `Edit ${source}` })
      .click();
    await page.getByRole("button", { name: "Duplicate" }).click();
    const copyName = `${source} (copy)`;
    await expect(page.getByRole("heading", { name: `Edit ${copyName}`, level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Save role" }).click();
    await expect(roleRow(page, copyName)).toBeVisible();

    await roleRow(page, copyName)
      .getByRole("button", { name: `Delete ${copyName}` })
      .click();
    await page
      .getByRole("dialog", { name: "Delete role template" })
      .getByRole("button", { name: "Delete role" })
      .click();
    await expect(roleRow(page, copyName)).toHaveCount(0);

    await roleRow(page, source)
      .getByRole("button", { name: `Delete ${source}` })
      .click();
    await page
      .getByRole("dialog", { name: "Delete role template" })
      .getByRole("button", { name: "Delete role" })
      .click();
    await expect(roleRow(page, source)).toHaveCount(0);
  });

  test("creates, toggles and deletes an agent", async ({ page }) => {
    await login(page);
    await openSettings(page);

    await page.getByRole("button", { name: "New agent" }).click();
    await expect(page.getByRole("heading", { name: "New AI agent", level: 1 })).toBeVisible();
    const generated = await page.getByLabel("Agent name").inputValue();
    expect(generated.trim().length).toBeGreaterThan(2);

    const agentName = uniqueName("E2E Agent");
    await page.getByLabel("Agent name").fill(agentName);
    await page.getByLabel("Role template").selectOption({ label: "QA Engineer" });
    await page.getByLabel("API base URL").fill("http://127.0.0.1:8099/v1");
    await page.getByLabel("Model identifier").fill("local-test-model");
    await page.getByLabel("API key (optional)").fill("sk-e2e-secret-9999");
    await page.getByRole("button", { name: "Save agent" }).click();

    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
    const row = agentRow(page, agentName);
    await expect(row).toContainText("QA Engineer");
    await expect(row).toContainText("local-test-model");
    await expect(page.locator("body")).not.toContainText("sk-e2e-secret");

    await row.getByRole("button", { name: `Disable ${agentName}` }).click();
    await expect(agentRow(page, agentName)).toContainText("disabled");
    await agentRow(page, agentName)
      .getByRole("button", { name: `Enable ${agentName}` })
      .click();
    await expect(agentRow(page, agentName)).toContainText("enabled");

    await agentRow(page, agentName)
      .getByRole("button", { name: `Delete ${agentName}` })
      .click();
    const dialog = page.getByRole("dialog", { name: "Delete agent" });
    await dialog.getByRole("button", { name: "Delete agent" }).click();
    await expect(agentRow(page, agentName)).toHaveCount(0);
  });
});
