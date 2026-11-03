import { api } from "@/lib/api";
import type { Card } from "@/lib/types";
import { optionalText, stringSchema, type McpTool } from "./toolSchema";

/** One column of the active Loop as the overview tool reports it. */
export interface LoopColumn {
  id: string;
  name: string;
  card_count: number;
}

export function loopTools(options: {
  boardId: string;
  loopId: string;
  loopName: string;
  columns: LoopColumn[];
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
          lists: options.columns,
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
          list_id: optionalText(input.list_id),
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
          description: optionalText(input.description) ?? "",
          priority: (input.priority ?? "none") as Card["priority"],
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
          q: optionalText(input.query),
          label: optionalText(input.label),
          priority: input.priority as Card["priority"] | undefined,
          overdue: input.overdue === true,
          limit: 50,
        });
        return {
          cards: items.map((card) => ({ id: card.id, title: card.title, list_id: card.list_id })),
        };
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
