import { expect, test } from "playwright/test";
import { LEGACY_VERSION, legacyConnect, legacyPost, legacyRpc, mcpToolNames } from "./mcp";
import { issueToken, login } from "./support";
import * as plan from "./worker-plan";

/**
 * `/mcp` speaks MCP 2026-07-28 and the older 2025-06-18 on the same address. A key connects with
 * the older handshake, sees the same tools as a client of the newer revision, and calls one.
 */
test.describe("both MCP revisions on /mcp", () => {
  test("a client of 2025-06-18 connects with initialize and lists the tools", async ({ page }) => {
    await login(page);
    const token = await issueToken(page, plan.WORKER_SCOPES);

    await test.step("initialize names 2025-06-18 and mints no session", async () => {
      const { initialize, sessionId } = await legacyConnect(page, token);
      expect(initialize.protocolVersion).toBe(LEGACY_VERSION);
      expect(initialize.serverInfo.name).toBe("tralala");
      expect(initialize.capabilities).toEqual({ tools: { listChanged: false } });
      expect(initialize.instructions).toContain("whoami");
      expect(sessionId).toBeUndefined();
    });

    await test.step("tools/list offers the same tools as revision 2026-07-28", async () => {
      const listed = await legacyRpc(page, token, "tools/list");
      expect(listed.resultType).toBeUndefined();
      const names = (listed.tools as { name: string }[]).map((entry) => entry.name);
      expect(names).toContain("whoami");
      expect(names).toContain("set_ticket_wait");
      expect(names).toEqual(await mcpToolNames(page, token));
    });

    await test.step("ping answers, and a tool call goes through", async () => {
      expect(await legacyRpc(page, token, "ping")).toEqual({});
      const called = await legacyRpc(page, token, "tools/call", { name: "whoami", arguments: {} });
      expect(called.isError).toBe(false);
      const whoami = called.structuredContent as { scopes: string[] };
      expect(whoami.scopes).toEqual([...plan.WORKER_SCOPES].sort());
    });

    await test.step("a version neither revision speaks is refused with -32022", async () => {
      const refused = await legacyPost(page, token, { id: 99, method: "tools/list" }, "2025-11-25");
      expect(refused.status()).toBe(400);
      const body = (await refused.json()) as {
        error: { code: number; data: { supported: string[]; requested: string } };
      };
      expect(body.error.code).toBe(-32022);
      expect(body.error.data).toEqual({
        supported: ["2026-07-28", LEGACY_VERSION],
        requested: "2025-11-25",
      });
    });
  });
});
