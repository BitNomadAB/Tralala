import { expect, test } from "playwright/test";
import { ADMIN, login, uniqueName } from "./support";

test.describe("settings", () => {
  test("switches themes and persists the choice across reloads", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: "Settings" }).click();

    await expect(page.getByRole("radio", { name: /Dark/ })).toHaveAttribute("aria-checked", "true");
    await page.getByRole("radio", { name: /Light/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    await page.reload();
    await expect(page.getByRole("radio", { name: /Light/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    await page.getByRole("radio", { name: /Dark/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    await expect(page.getByRole("radio", { name: /CareNomad/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await page.getByRole("radio", { name: /MatchMap/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme-kit", "matchmap");

    await page.reload();
    await expect(page.getByRole("radio", { name: /MatchMap/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(page.locator("html")).toHaveAttribute("data-theme-kit", "matchmap");

    await page.getByRole("radio", { name: /CareNomad/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme-kit", "carenomad");
  });

  test("the appearance choice belongs to the account, not the browser", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByRole("radio", { name: /MatchMap/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme-kit", "matchmap");

    const name = uniqueName("theme").replace(/\s+/g, "-").toLowerCase();
    await page.getByRole("button", { name: "New user" }).click();
    const dialog = page.getByRole("dialog", { name: "New user" });
    await dialog.getByLabel("Username").fill(name);
    await dialog.getByLabel("Initial password").fill("member-password-1");
    await dialog.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByText(name, { exact: false })).toBeVisible();

    const signIn = async (username: string, password: string) => {
      await page.getByRole("button", { name: "Sign out" }).click();
      await page.getByLabel("Username").fill(username);
      await page.getByLabel("Password").fill(password);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
    };

    // The new account starts from the default kit even though this browser last showed MatchMap.
    await signIn(name, "member-password-1");
    await expect(page.locator("html")).toHaveAttribute("data-theme-kit", "carenomad");

    // And the administrator's own choice is still there.
    await signIn(ADMIN.username, ADMIN.password);
    await expect(page.locator("html")).toHaveAttribute("data-theme-kit", "matchmap");

    // Leave the shared administrator account on its default for the other specs.
    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByRole("radio", { name: /CareNomad/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme-kit", "carenomad");
  });

  test("issues and revokes an interaction agent access", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: "Settings" }).click();
    const agentName = uniqueName("Agent");

    await page.getByRole("button", { name: "New access key" }).click();
    const dialog = page.getByRole("dialog", { name: "New interaction agent access" });
    await dialog.getByLabel("Agent name").fill(agentName);
    // The scope list arrives with /meta; wait for it so the click hits a rendered checkbox.
    await expect(dialog.getByLabel("boards:read")).toBeVisible();
    await dialog.getByLabel("cards:write").check();
    await dialog.getByRole("button", { name: "Create access" }).click();

    const issued = page.getByRole("dialog", { name: "Copy this token now" });
    const token = await issued.getByLabel("New API token").inputValue();
    expect(token).toMatch(/^trl_[A-Za-z0-9_-]{20,}$/);
    await issued.getByRole("button", { name: "Done" }).click();

    const row = page.getByRole("listitem").filter({ hasText: agentName });
    await expect(row).toContainText("boards:read, cards:read, cards:write");
    await expect(row).toContainText("never used");
    await expect(row.getByText("active", { exact: true })).toBeVisible();

    await row.getByRole("button", { name: `Revoke ${agentName}` }).click();
    await expect(row.getByText("revoked", { exact: true })).toBeVisible();
  });
});
