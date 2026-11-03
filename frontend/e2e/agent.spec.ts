import { expect, request as playwrightRequest, test } from "playwright/test";
import {
  addCard,
  boardIdFromUrl,
  boardWithLoop,
  cardTile,
  csrfToken,
  login,
  resolveLoopId,
  uniqueName,
} from "./support";

test.describe("agent access", () => {
  test("an agent token can work on cards but cannot create boards, and is audited", async ({
    page,
  }) => {
    await login(page);
    const boardName = uniqueName("Agent board");
    await boardWithLoop(page, boardName);
    const boardId = boardIdFromUrl(page);
    const loopId = await resolveLoopId(page, boardId);

    const listsResponse = await page.request.get(`/api/v1/boards/${boardId}/loops/${loopId}/lists`);
    expect(listsResponse.ok()).toBe(true);
    const lists = (await listsResponse.json()).data as { id: string; name: string }[];
    const todo = lists.find((list) => list.name === "Todo");
    if (!todo) throw new Error("Todo list missing");

    const credentialResponse = await page.request.post("/api/v1/credentials", {
      headers: { "X-CSRF-Token": await csrfToken(page) },
      data: {
        name: uniqueName("agent-token"),
        scopes: ["boards:read", "cards:read", "cards:write", "comments:write"],
        expires_in_days: 1,
      },
    });
    expect(credentialResponse.status()).toBe(201);
    const credential = (await credentialResponse.json()).data as { token: string };

    const agent = await playwrightRequest.newContext({
      baseURL: new URL(page.url()).origin,
      extraHTTPHeaders: { Authorization: `Bearer ${credential.token}` },
    });

    const created = await agent.post(`/api/v1/boards/${boardId}/loops/${loopId}/cards`, {
      data: { list_id: todo.id, title: "Agent-created task", priority: "medium" },
    });
    expect(created.status()).toBe(201, await created.text());
    const card = (await created.json()).data as { id: string; version: number };
    expect(card.version).toBe(1);

    const moved = await agent.post(
      `/api/v1/boards/${boardId}/loops/${loopId}/cards/${card.id}/move`,
      {
        data: {
          version: 1,
          list_id: lists.find((list) => list.name === "Done")?.id,
          position: 0,
        },
      },
    );
    expect(moved.status()).toBe(200);

    const forbidden = await agent.post("/api/v1/boards", { data: { name: "Should fail" } });
    expect(forbidden.status()).toBe(403);
    expect((await forbidden.json()).error.code).toBe("forbidden");

    await page.reload();
    await expect(cardTile(page, "Done", "Agent-created task")).toBeVisible();

    await page.getByRole("button", { name: "Activity" }).click();
    const activity = page.getByRole("complementary", { name: "Board activity" });
    await expect(activity).toContainText("card.created");
    await expect(activity.getByText("agent", { exact: true }).first()).toBeVisible();
    await agent.dispose();
  });

  test("a revoked token is rejected immediately", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Revoke board"));

    const credentialResponse = await page.request.post("/api/v1/credentials", {
      headers: { "X-CSRF-Token": await csrfToken(page) },
      data: { name: uniqueName("short-lived"), scopes: ["boards:read"] },
    });
    const credential = (await credentialResponse.json()).data as { id: string; token: string };

    const agent = await playwrightRequest.newContext({
      baseURL: new URL(page.url()).origin,
      extraHTTPHeaders: { Authorization: `Bearer ${credential.token}` },
    });
    expect((await agent.get("/api/v1/boards")).status()).toBe(200);

    await page.request.post(`/api/v1/credentials/${credential.id}/revoke`, {
      headers: { "X-CSRF-Token": await csrfToken(page) },
    });

    const after = await agent.get("/api/v1/boards");
    expect(after.status()).toBe(401);
    expect((await after.json()).error.code).toBe("token_revoked");
    await agent.dispose();
  });
});

test.describe("browser safety", () => {
  test("card Markdown cannot inject HTML", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("XSS board"));
    await addCard(page, "Todo", "Unsafe card");

    const dialog = page.getByRole("dialog");
    await page
      .getByRole("region", { name: "List Todo" })
      .getByRole("button", { name: "Unsafe card" })
      .click();
    await expect(dialog).toBeVisible();
    await dialog
      .getByLabel("Card description (Markdown)")
      .fill('<script>window.__pwned = true</script> <img src=x onerror="window.__pwned = true">');
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await dialog.getByRole("button", { name: "Preview" }).click();

    await expect(dialog).toContainText("<script>");
    const pwned = await page.evaluate(() => (window as unknown as { __pwned?: boolean }).__pwned);
    expect(pwned).toBeUndefined();
    expect(await dialog.locator("img").count()).toBe(0);
  });
});
