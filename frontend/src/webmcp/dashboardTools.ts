import { api } from "@/lib/api";
import { boardIdSchema, optionalText, stringSchema, type McpTool } from "./toolSchema";

export function dashboardTools(options: { onOpenBoard: (boardId: string) => void }): McpTool[] {
  return [
    {
      name: "list_boards",
      description: "List Tralala boards with status, list and card counts.",
      requiredScope: "boards:read",
      inputSchema: {
        type: "object",
        properties: { status: { type: "string", enum: ["active", "archived"] } },
        additionalProperties: false,
      },
      execute: async (input) => {
        const { items } = await api.listBoards({ status: input.status as string | undefined });
        return {
          boards: items.map((board) => ({
            id: board.id,
            name: board.name,
            status: board.status,
            loop_count: board.loop_count,
            list_count: board.list_count,
            card_count: board.card_count,
          })),
        };
      },
    },
    {
      name: "list_board_templates",
      description: "List saved board templates usable as a starting point for a new board.",
      requiredScope: "boards:read",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: async () => {
        const templates = await api.listTemplates();
        return {
          templates: templates.map((template) => ({
            id: template.id,
            name: template.name,
            description: template.description,
            lists: template.lists,
          })),
        };
      },
    },
    {
      name: "create_board",
      description: "Create a board with its own SQLite database.",
      requiredScope: "boards:write",
      inputSchema: {
        type: "object",
        properties: {
          name: stringSchema("Board name"),
          description: stringSchema("Description"),
          template_id: stringSchema("Optional board template id"),
        },
        required: ["name"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const board = await api.createBoard({
          name: String(input.name),
          description: optionalText(input.description) ?? "",
          template_id: optionalText(input.template_id) ?? null,
        });
        options.onOpenBoard(board.id);
        return { id: board.id, name: board.name };
      },
    },
    {
      name: "search_boards",
      description: "Search boards by name or description.",
      requiredScope: "boards:read",
      inputSchema: {
        type: "object",
        properties: { query: stringSchema("Search text") },
        required: ["query"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const { items } = await api.listBoards({ q: String(input.query) });
        return { boards: items.map((board) => ({ id: board.id, name: board.name })) };
      },
    },
    {
      name: "open_board",
      description: "Navigate to a board in the application.",
      requiredScope: "boards:read",
      inputSchema: {
        type: "object",
        properties: { board_id: boardIdSchema },
        required: ["board_id"],
        additionalProperties: false,
      },
      execute: (input) => {
        options.onOpenBoard(String(input.board_id));
        return { opened: input.board_id };
      },
    },
  ];
}
