import { api } from "@/lib/api";
import type { Card } from "@/lib/types";
import { optionalText, stringSchema, type McpTool } from "./toolSchema";

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
          title: optionalText(input.title),
          // An empty string is kept here: it clears the description.
          description: typeof input.description === "string" ? input.description : undefined,
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
