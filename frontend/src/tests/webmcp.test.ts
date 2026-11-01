import { describe, expect, it, vi } from "vitest";
import { createRegistry } from "@/webmcp/registry";
import { isWebMcpAvailable, getModelContext, type ModelContextApi } from "@/webmcp/capability";
import { boardTools, cardTools, dashboardTools } from "@/webmcp/tools";

function fakeApi() {
  const registerTool = vi.fn().mockResolvedValue(undefined);
  const unregisterTool = vi.fn().mockResolvedValue(undefined);
  const api: ModelContextApi = { registerTool, unregisterTool };
  return { api, registerTool, unregisterTool };
}

describe("webmcp capability detection", () => {
  it("reports unavailable when no modelContext exists", () => {
    expect(getModelContext()).toBeNull();
    expect(isWebMcpAvailable()).toBe(false);
  });

  it("detects document.modelContext", () => {
    const { api } = fakeApi();
    (document as unknown as { modelContext?: ModelContextApi }).modelContext = api;
    expect(getModelContext()).toBe(api);
    expect(isWebMcpAvailable()).toBe(true);
    delete (document as unknown as { modelContext?: ModelContextApi }).modelContext;
  });
});

describe("webmcp registry", () => {
  it("registers tools and ignores duplicates", async () => {
    const { api, registerTool } = fakeApi();
    const registry = createRegistry(api);
    const tools = dashboardTools({ onOpenBoard: () => undefined });
    await registry.register(tools);
    await registry.register(tools);
    expect(registerTool).toHaveBeenCalledTimes(tools.length);
    expect(registry.registeredNames()).toHaveLength(tools.length);
  });

  it("unregisters tools on dispose", async () => {
    const { api, unregisterTool } = fakeApi();
    const registry = createRegistry(api);
    await registry.register(dashboardTools({ onOpenBoard: () => undefined }));
    registry.dispose();
    expect(unregisterTool).toHaveBeenCalled();
    expect(registry.registeredNames()).toEqual([]);
  });

  it("keeps registering after one failing tool", async () => {
    const registerTool = vi
      .fn()
      .mockRejectedValueOnce(new Error("rejected"))
      .mockResolvedValue(undefined);
    const registry = createRegistry({ registerTool });
    await registry.register(dashboardTools({ onOpenBoard: () => undefined }));
    expect(registry.registeredNames().length).toBeGreaterThan(0);
  });
});

describe("webmcp tool definitions", () => {
  it("expose stable names and required scopes per context", () => {
    const names = {
      dashboard: dashboardTools({ onOpenBoard: () => undefined }).map((tool) => tool.name),
      board: boardTools({
        boardId: "b",
        boardName: "Board",
        lists: [],
        cardsByList: {},
        onOpenCard: () => undefined,
      }).map((tool) => tool.name),
      card: cardTools({ boardId: "b", cardId: "c", onClose: () => undefined }).map(
        (tool) => tool.name,
      ),
    };
    expect(names.dashboard).toEqual([
      "list_boards",
      "list_board_templates",
      "create_board",
      "search_boards",
      "open_board",
    ]);
    expect(names.board).toContain("get_board_overview");
    expect(names.board).toContain("move_card");
    expect(names.card).toEqual([
      "get_card_details",
      "update_card",
      "add_comment",
      "update_checklist",
      "archive_card",
    ]);
    expect(boardTools({
      boardId: "b",
      boardName: "Board",
      lists: [],
      cardsByList: {},
      onOpenCard: () => undefined,
    }).find((tool) => tool.name === "create_card")?.requiredScope).toBe("cards:write");
  });

  it("every tool declares a JSON input schema", () => {
    const tools = [
      ...dashboardTools({ onOpenBoard: () => undefined }),
      ...cardTools({ boardId: "b", cardId: "c", onClose: () => undefined }),
    ];
    for (const tool of tools) {
      expect(tool.inputSchema).toMatchObject({ type: "object" });
      expect(typeof tool.execute).toBe("function");
    }
  });
});
