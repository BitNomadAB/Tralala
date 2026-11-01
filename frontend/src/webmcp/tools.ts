import { api } from "@/lib/api";
import type { BoardList, Card } from "@/lib/types";
import type { ModelContextToolDefinition } from "./capability";

export interface McpTool extends ModelContextToolDefinition {
  requiredScope?: string;
}

const stringSchema = (description: string) => ({ type: "string", description });

const boardIdSchema = stringSchema("Board identifier");

export function dashboardTools(options: {
  onOpenBoard: (boardId: string) => void;
}): McpTool[] {
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
        return { boards: items.map((board) => ({
          id: board.id,
          name: board.name,
          status: board.status,
          loop_count: board.loop_count,
          list_count: board.list_count,
          card_count: board.card_count,
        })) };
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
          description: input.description ? String(input.description) : "",
          template_id: input.template_id ? String(input.template_id) : null,
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

export function loopTools(options: {
  boardId: string;
  loopId: string;
  loopName: string;
  lists: BoardList[];
  cardsByList: Record<string, Card[]>;
  onOpenCard: (cardId: string) => void;
}): McpTool[] {
  const { boardId, loopId } = options;
  return [
    {
      name: "get_loop_overview",
      description:
        "Summarise the active Loop: stage, document states, published phases and column counts.",
      requiredScope: "loops:read",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: async () => {
        const [loop, readiness] = await Promise.all([
          api.getLoop(boardId, loopId),
          api.getReadiness(boardId, loopId),
        ]);
        return {
          board_id: boardId,
          loop_id: loopId,
          name: loop.name,
          key: loop.key,
          stage: loop.stage,
          documents: Object.fromEntries(
            Object.entries(loop.documents).map(([kind, document]) => [kind, document.state]),
          ),
          execution_allowed: readiness.execution_allowed,
          phases: readiness.phases.map((phase) => ({
            number: phase.number,
            name: phase.name,
            state: phase.state,
            blocked_by: phase.blocked_by.map((blocker) => blocker.reason),
          })),
          lists: options.lists.map((list) => ({
            id: list.id,
            name: list.name,
            card_count: (options.cardsByList[list.id] ?? []).length,
          })),
        };
      },
    },
    {
      name: "get_loop_plan",
      description: "Read the approved plan with per-Ticket readiness, blockers and human gates.",
      requiredScope: "loops:read",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: async () => {
        const readiness = await api.getReadiness(boardId, loopId);
        return {
          loop_id: loopId,
          stage: readiness.stage,
          execution_allowed: readiness.execution_allowed,
          tickets: readiness.items.map((item) => ({
            key: item.key,
            title: item.title,
            phase_number: item.phase_number,
            ready: item.ready,
            human_action_required: item.human_action_required,
            blockers: item.blockers.map((blocker) => blocker.reason),
          })),
        };
      },
    },
    {
      name: "request_generation",
      description:
        "Ask the configured agent to draft the analysis or the RoadMap for this Loop. Generation never approves a document.",
      requiredScope: "loops:generate",
      inputSchema: {
        type: "object",
        properties: {
          purpose: { type: "string", enum: ["analysis", "roadmap", "qa"] },
        },
        required: ["purpose"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const run = await api.startGeneration(
          boardId,
          loopId,
          String(input.purpose) as "analysis" | "roadmap" | "qa",
        );
        return { run_id: run.id, status: run.status, purpose: run.purpose };
      },
    },
    {
      name: "list_loop_tickets",
      description: "List Tickets on the active Loop, optionally limited to one column.",
      requiredScope: "cards:read",
      inputSchema: {
        type: "object",
        properties: { list_id: stringSchema("Optional list identifier") },
        additionalProperties: false,
      },
      execute: async (input) => {
        const cards = await api.listCards(boardId, loopId, {
          list_id: input.list_id ? String(input.list_id) : undefined,
          limit: 200,
        });
        return {
          cards: cards.map((card) => ({
            id: card.id,
            list_id: card.list_id,
            title: card.title,
            priority: card.priority,
            due_at: card.due_at,
            completed: Boolean(card.completed_at),
            ticket_key: card.ticket_key,
            ready: card.ready,
            human_action_required: card.human_action_required,
            labels: card.labels.map((label) => label.name),
          })),
        };
      },
    },
    {
      name: "create_list",
      description: "Create a list on the active board.",
      requiredScope: "cards:write",
      inputSchema: {
        type: "object",
        properties: { name: stringSchema("List name") },
        required: ["name"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const list = await api.createList(boardId, loopId, String(input.name));
        return { id: list.id, name: list.name };
      },
    },
    {
      name: "create_card",
      description: "Create a card in a list of the active board.",
      requiredScope: "cards:write",
      inputSchema: {
        type: "object",
        properties: {
          list_id: stringSchema("Target list identifier"),
          title: stringSchema("Card title"),
          description: stringSchema("Markdown description"),
          priority: { type: "string", enum: ["none", "low", "medium", "high", "urgent"] },
        },
        required: ["list_id", "title"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const card = await api.createCard(boardId, loopId, {
          list_id: String(input.list_id),
          title: String(input.title),
          description: input.description ? String(input.description) : "",
          priority: (input.priority as Card["priority"]) ?? "none",
        });
        return { id: card.id, version: card.version, list_id: card.list_id };
      },
    },
    {
      name: "search_cards",
      description: "Search cards on the active board by text, label, priority or overdue state.",
      requiredScope: "cards:read",
      inputSchema: {
        type: "object",
        properties: {
          query: stringSchema("Full text query"),
          label: stringSchema("Label name or id"),
          priority: { type: "string", enum: ["none", "low", "medium", "high", "urgent"] },
          overdue: { type: "boolean" },
        },
        additionalProperties: false,
      },
      execute: async (input) => {
        const { items } = await api.searchCards(boardId, loopId, {
          q: input.query ? String(input.query) : undefined,
          label: input.label ? String(input.label) : undefined,
          priority: input.priority as Card["priority"] | undefined,
          overdue: input.overdue === true,
          limit: 50,
        });
        return { cards: items.map((card) => ({ id: card.id, title: card.title, list_id: card.list_id })) };
      },
    },
    {
      name: "open_card",
      description: "Open a card's detail panel.",
      requiredScope: "cards:read",
      inputSchema: {
        type: "object",
        properties: { card_id: stringSchema("Card identifier") },
        required: ["card_id"],
        additionalProperties: false,
      },
      execute: (input) => {
        options.onOpenCard(String(input.card_id));
        return { opened: input.card_id };
      },
    },
    {
      name: "move_card",
      description: "Move a card to another list on the active board.",
      requiredScope: "cards:write",
      inputSchema: {
        type: "object",
        properties: {
          card_id: stringSchema("Card identifier"),
          list_id: stringSchema("Destination list identifier"),
          position: { type: "number", minimum: 0 },
          version: { type: "number", minimum: 1 },
        },
        required: ["card_id", "list_id", "version"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const card = await api.moveCard(boardId, loopId, String(input.card_id), {
          version: Number(input.version),
          list_id: String(input.list_id),
          position: typeof input.position === "number" ? input.position : 0,
        });
        return { id: card.id, list_id: card.list_id, version: card.version };
      },
    },
  ];
}

export function cardTools(options: {
  boardId: string;
  loopId: string;
  cardId: string;
  onClose: () => void;
}): McpTool[] {
  const { boardId, loopId, cardId } = options;
  return [
    {
      name: "get_card_details",
      description: "Read the open card with checklists and comments.",
      requiredScope: "cards:read",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: async () => {
        const card = await api.getCard(boardId, loopId, cardId);
        return {
          id: card.id,
          title: card.title,
          description: card.description,
          priority: card.priority,
          due_at: card.due_at,
          completed: Boolean(card.completed_at),
          labels: card.labels.map((label) => label.name),
          checklists: (card.checklists ?? []).map((checklist) => ({
            id: checklist.id,
            title: checklist.title,
            items: checklist.items.map((item) => ({
              id: item.id,
              text: item.text,
              completed: item.completed,
            })),
          })),
          comments: (card.comments ?? []).map((comment) => ({
            id: comment.id,
            actor: comment.actor_name,
            content: comment.content,
          })),
          version: card.version,
        };
      },
    },
    {
      name: "update_card",
      description: "Update the open card. Requires the current version.",
      requiredScope: "cards:write",
      inputSchema: {
        type: "object",
        properties: {
          version: { type: "number", minimum: 1 },
          title: stringSchema("New title"),
          description: stringSchema("New Markdown description"),
          priority: { type: "string", enum: ["none", "low", "medium", "high", "urgent"] },
          completed: { type: "boolean" },
        },
        required: ["version"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const card = await api.updateCard(boardId, loopId, cardId, {
          version: Number(input.version),
          title: input.title ? String(input.title) : undefined,
          description: input.description !== undefined ? String(input.description) : undefined,
          priority: input.priority as Card["priority"] | undefined,
          completed: typeof input.completed === "boolean" ? input.completed : undefined,
        });
        return { id: card.id, version: card.version };
      },
    },
    {
      name: "add_comment",
      description: "Add a comment to the open card.",
      requiredScope: "comments:write",
      inputSchema: {
        type: "object",
        properties: { content: stringSchema("Comment text") },
        required: ["content"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const comment = await api.addComment(boardId, loopId, cardId, String(input.content));
        return { id: comment.id };
      },
    },
    {
      name: "update_checklist",
      description: "Add an item to a checklist on the open card.",
      requiredScope: "cards:write",
      inputSchema: {
        type: "object",
        properties: {
          checklist_id: stringSchema("Checklist identifier"),
          text: stringSchema("Item text"),
        },
        required: ["checklist_id", "text"],
        additionalProperties: false,
      },
      execute: async (input) => {
        const item = await api.addChecklistItem(
          boardId,
          String(input.checklist_id),
          String(input.text),
        );
        return { id: item.id, completed: item.completed };
      },
    },
    {
      name: "archive_card",
      description: "Archive the open card.",
      requiredScope: "cards:write",
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
      execute: async () => {
        const card = await api.archiveCard(boardId, loopId, cardId);
        options.onClose();
        return { id: card.id, archived: true };
      },
    },
  ];
}
