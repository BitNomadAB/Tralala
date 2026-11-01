import { expect, test } from "playwright/test";
import { boardIdFromUrl, boardWithLoop, csrfToken, login, uniqueName } from "./support";

test.describe("board lifecycle", () => {
  test("archives and restores a board from the dashboard", async ({ page }) => {
    await login(page);
    const boardName = uniqueName("Lifecycle board");
    await boardWithLoop(page, boardName);

    await page.getByRole("link", { name: "Boards" }).click();
    const row = page.getByRole("listitem").filter({ hasText: boardName });
    await expect(row.getByText("active", { exact: true })).toBeVisible();
    await expect(row.getByRole("button", { name: `Delete ${boardName}` })).toBeDisabled();

    await row.getByRole("button", { name: `Archive ${boardName}` }).click();
    await expect(row.getByText("archived", { exact: true })).toBeVisible();
    await expect(row.getByRole("button", { name: `Delete ${boardName}` })).toBeEnabled();

    await page.getByLabel("Filter by status").selectOption("archived");
    await expect(page.getByRole("listitem").filter({ hasText: boardName })).toBeVisible();

    await row.getByRole("button", { name: `Restore ${boardName}` }).click();
    await expect(row).toHaveCount(0);

    await page.getByLabel("Filter by status").selectOption("");
    const restored = page.getByRole("listitem").filter({ hasText: boardName });
    await expect(restored.getByText("active", { exact: true })).toBeVisible();
  });

  test("exposes an export archive and an integrity report through the API", async ({ page }) => {
    await login(page);
    const boardName = uniqueName("Export board");
    await boardWithLoop(page, boardName);
    const boardId = boardIdFromUrl(page);

    const exported = await page.request.get(`/api/v1/boards/${boardId}/export`);
    expect(exported.status()).toBe(200);
    expect(exported.headers()["content-type"]).toContain("application/zip");
    const body = await exported.body();
    expect(body.subarray(0, 2).toString()).toBe("PK");

    const validation = await page.request.get(`/api/v1/boards/${boardId}/validate`);
    expect(validation.status()).toBe(200);
    const payload = await validation.json();
    expect(payload.data.ok).toBe(true);
    expect(payload.data.counts.lists).toBe(5); // five Loop-owned columns

    const backup = await page.request.post(`/api/v1/boards/${boardId}/backups`, {
      headers: { "X-CSRF-Token": await csrfToken(page) },
    });
    expect(backup.status()).toBe(201);
    const backupBody = await backup.json();
    expect(backupBody.data.verification.ok).toBe(true);

    const restored = await page.request.post(
      `/api/v1/boards/${boardId}/backups/${backupBody.data.name}/restore`,
      { headers: { "X-CSRF-Token": await csrfToken(page) } },
    );
    expect(restored.status()).toBe(200);
    expect((await restored.json()).data.verification.ok).toBe(true);
  });
});
