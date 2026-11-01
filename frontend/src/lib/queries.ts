import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export const keys = {
  me: ["me"] as const,
  boards: (filters: Record<string, string | number | undefined>) => ["boards", filters] as const,
  board: (boardId: string) => ["board", boardId] as const,
  lists: (boardId: string) => ["lists", boardId] as const,
  listCards: (boardId: string, listId: string, limit: number) =>
    ["cards", boardId, listId, limit] as const,
  boardCardsPrefix: (boardId: string) => ["cards", boardId] as const,
  card: (boardId: string, cardId: string) => ["card", boardId, cardId] as const,
  mentions: (boardId: string, cardId: string) => ["mentions", boardId, cardId] as const,
  search: (boardId: string, params: Record<string, unknown>) =>
    ["search", boardId, params] as const,
  labels: (boardId: string) => ["labels", boardId] as const,
  activity: (boardId: string, entityId?: string) =>
    ["activity", boardId, entityId ?? "board"] as const,
  credentials: ["credentials"] as const,
  templates: ["templates"] as const,
  roleTemplates: ["role-templates"] as const,
  roleTemplate: (roleId: string) => ["role-template", roleId] as const,
  agents: ["agents"] as const,
  agentDirectory: ["agent-directory"] as const,
  agent: (agentId: string) => ["agent", agentId] as const,
  discussionBoards: ["discussion-boards"] as const,
  discussions: (boardId: string) => ["discussions", boardId] as const,
};

export function useBoards(filters: {
  q?: string;
  status?: string;
  sort?: string;
  order?: string;
  limit?: number;
}) {
  return useQuery({
    queryKey: keys.boards(filters),
    queryFn: () => api.listBoards(filters),
  });
}

export function useBoard(boardId: string) {
  return useQuery({
    queryKey: keys.board(boardId),
    queryFn: () => api.getBoard(boardId),
    enabled: Boolean(boardId),
  });
}

export function useLists(boardId: string) {
  return useQuery({
    queryKey: keys.lists(boardId),
    queryFn: () => api.listLists(boardId),
    enabled: Boolean(boardId),
  });
}

export function useListCards(boardId: string, listId: string, limit: number) {
  return useQuery({
    queryKey: keys.listCards(boardId, listId, limit),
    queryFn: () => api.listCards(boardId, { list_id: listId, limit }),
    enabled: Boolean(boardId && listId),
  });
}

export function useLabels(boardId: string) {
  return useQuery({
    queryKey: keys.labels(boardId),
    queryFn: () => api.listLabels(boardId),
    enabled: Boolean(boardId),
  });
}

export function useTemplates() {
  return useQuery({
    queryKey: keys.templates,
    queryFn: () => api.listTemplates(),
  });
}

export function useRoleTemplates() {
  return useQuery({
    queryKey: keys.roleTemplates,
    queryFn: () => api.listRoleTemplates(),
  });
}

export function useRoleTemplate(roleId: string) {
  return useQuery({
    queryKey: keys.roleTemplate(roleId),
    queryFn: () => api.getRoleTemplate(roleId),
    enabled: Boolean(roleId) && roleId !== "new",
  });
}

export function useAgents() {
  return useQuery({
    queryKey: keys.agents,
    queryFn: () => api.listAgents(),
  });
}

export function useAgent(agentId: string) {
  return useQuery({
    queryKey: keys.agent(agentId),
    queryFn: () => api.getAgent(agentId),
    enabled: Boolean(agentId) && agentId !== "new",
  });
}

export function useActivity(boardId: string, entityId?: string) {
  return useQuery({
    queryKey: keys.activity(boardId, entityId),
    queryFn: () => api.listActivity(boardId, { entity_id: entityId, limit: 50 }),
    enabled: Boolean(boardId),
  });
}
