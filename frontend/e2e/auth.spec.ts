import { expect, test } from "playwright/test";
import { ADMIN, login } from "./support";

test.describe("authentication", () => {
  test("rejects invalid credentials without creating a session", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Username").fill(ADMIN.username);
    await page.getByLabel("Password").fill("definitely-wrong");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByRole("alert")).toContainText(/invalid credentials/i);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    const cookies = await page.context().cookies();
    expect(cookies.some((cookie) => cookie.name === "tralala_session")).toBe(false);
  });

  test("signs in, keeps the session across reloads, and signs out", async ({ page }) => {
    await login(page);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });
});
