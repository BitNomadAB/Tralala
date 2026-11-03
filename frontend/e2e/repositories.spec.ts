import { expect, test } from "playwright/test";
import { login, uniqueName } from "./support";

// The repositories page is the one settings screen with no journey of its own: it stores a repository
// the analysis agents may read and a sealed token for it. Nothing here needs GitHub, because saving a
// repository only validates the URL and the token is optional.
test.describe("repositories", () => {
  test("adds, edits and removes a repository the agents may read", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByRole("link", { name: "Manage repositories" }).click();

    await expect(page.getByRole("heading", { name: "Repositories", level: 1 })).toBeVisible();

    const name = uniqueName("repo");
    await page.getByRole("button", { name: "New repository" }).click();
    const dialog = page.getByRole("dialog", { name: "New repository" });
    await dialog.getByLabel("Name").fill(name);
    await dialog.getByLabel("Repository URL").fill("https://github.com/BitNomadAB/Tralala");
    await dialog.getByLabel("Branch (optional)").fill("master");
    await dialog.getByRole("button", { name: "Save repository" }).click();

    const entry = page.getByRole("listitem").filter({ hasText: name });
    await expect(entry).toBeVisible();
    // No token was entered, so the row says so instead of pretending the repository is readable.
    await expect(entry.getByText("no token")).toBeVisible();
    await expect(entry.getByText("master")).toBeVisible();
    await expect(entry.getByText("https://github.com/BitNomadAB/Tralala")).toBeVisible();

    // A second save keeps the same repository: editing must not create a duplicate.
    await entry.getByRole("button", { name: "Edit" }).click();
    const editor = page.getByRole("dialog", { name: "Edit repository" });
    const renamed = `${name} renamed`;
    await editor.getByLabel("Name").fill(renamed);
    await editor.getByRole("button", { name: "Save repository" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: renamed })).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: name })).toHaveCount(1);

    await page
      .getByRole("listitem")
      .filter({ hasText: renamed })
      .getByRole("button", { name: "Remove" })
      .click();
    await expect(page.getByRole("listitem").filter({ hasText: renamed })).toHaveCount(0);
  });

  test("adds a Git over HTTPS repository, rebuilds its mirror and removes it", async ({ page }) => {
    // github.com is the default of TRALALA_REPOSITORY_HOSTS. Saving and rebuilding never reach the
    // host: the mirror is only fetched by a run, so a rebuild before any run removes nothing.
    await login(page);
    await page.goto("/settings/repositories");
    const name = uniqueName("mirror");
    const slug = name.replace(/\s+/g, "-").toLowerCase();
    await page.getByRole("button", { name: "New repository" }).click();
    const dialog = page.getByRole("dialog", { name: "New repository" });
    await dialog.getByLabel("Provider").selectOption("git_https");
    await dialog.getByLabel("Name").fill(name);
    await dialog.getByLabel("Repository URL").fill(`https://github.com/example/${slug}.git`);
    await dialog.getByRole("button", { name: "Save repository" }).click();

    const entry = page.getByRole("listitem").filter({ hasText: name });
    await expect(entry.getByText("Git over HTTPS")).toBeVisible();
    await expect(entry.getByText("no mirror")).toBeVisible();
    await entry.getByRole("button", { name: "Rebuild mirror" }).click();
    await expect(page.getByText("Mirror removed")).toBeVisible();

    await entry.getByRole("button", { name: "Remove", exact: true }).click();
    await expect(page.getByRole("listitem").filter({ hasText: name })).toHaveCount(0);
  });

  test("a member is told that only an administrator manages repositories", async ({ page }) => {
    await login(page);
    const name = uniqueName("repo-member").replace(/\s+/g, "-").toLowerCase();

    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByRole("button", { name: "New user" }).click();
    const dialog = page.getByRole("dialog", { name: "New user" });
    await dialog.getByLabel("Username").fill(name);
    await dialog.getByLabel("Initial password").fill("member-password-1");
    await dialog.getByRole("button", { name: "Create user" }).click();
    await expect(page.getByText(name, { exact: false })).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByLabel("Username").fill(name);
    await page.getByLabel("Password").fill("member-password-1");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();

    await page.goto("/settings/repositories");
    await expect(page.getByText("Only an administrator manages repository access.")).toBeVisible();
    await expect(page.getByRole("button", { name: "New repository" })).toHaveCount(0);
  });
});
