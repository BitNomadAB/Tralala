import { expect, test } from "playwright/test";
import { login, uniqueName } from "./support";

test("an administrator creates a member who cannot manage accounts", async ({ page }) => {
  await login(page);
  await page.goto("/settings");
  const name = uniqueName("member").replace(/\s+/g, "-").toLowerCase();
  const password = "member-password-1";

  await page.getByRole("button", { name: "New user" }).click();
  const dialog = page.getByRole("dialog", { name: "New user" });
  await dialog.getByLabel("Username").fill(name);
  await dialog.getByLabel("Initial password").fill(password);
  await dialog.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByText(name, { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Username").fill(name);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Your password" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Users" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "API credentials" })).toHaveCount(0);
});

test("the last enabled administrator cannot be disabled", async ({ page }) => {
  await login(page);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Disable admin" }).click();
  await expect(
    page.getByText("At least one enabled administrator must remain"),
  ).toBeVisible();
});
