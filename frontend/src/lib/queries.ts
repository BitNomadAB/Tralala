import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export const keys = {
  me: ["me"] as const,
  boards: (filters: Record<string, string | number | undefined>) => ["boards", filters] as const,
  board: (boardId: string) => ["board", boardId] as const,
  loops: (boardId: string, includeCompleted = false) =>
    ["loops", boardId, includeCompleted] as const,
  loop: (boardId: string, loopId: string) => ["loop", boardId, loopId] as const,
  loopDocuments: (boardId: string, loopId: string) => ["loop-documents", boardId, loopId] as const,
  loopPlan: (boardId: string, loopId: string) => ["loop-plan", boardId, loopId] as const,
  readiness: (boardId: string, loopId: string) => ["readiness", boardId, loopId] as const,
  qa: (boardId: string, loopId: string) => ["qa", boardId, loopId] as const,
  generationRuns: (boardId: string, loopId: string) =>
    ["generation-runs", boardId, loopId] as const,
  history: (boardId: string, params: Record<string, unknown>) =>
    ["history", boardId, params] as const,
  historyRecord: (boardId: string, historyId: string) =>
    ["history-record", boardId, historyId] as const,
  lists: (boardId: string, loopId: string) => ["lists", boardId, loopId] as const,
  listCards: (boardId: string, loopId: string, listId: string, limit: number) =>
    ["cards", boardId, loopId, listId, limit] as const,
  loopCardsPrefix: (boardId: string, loopId: string) => ["cards", boardId, loopId] as const,
  boardCardsPrefix: (boardId: string) => ["cards", boardId] as const,
  card: (boardId: string, loopId: string, cardId: string) =>
    ["card", boardId, loopId, cardId] as const,
  mentions: (boardId: string, loopId: string, cardId: string) =>
    ["mentions", boardId, loopId, cardId] as const,
  search: (boardId: string, loopId: string, params: Record<string, unknown>) =>
    ["search", boardId, loopId, params] as const,
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
  q?: string | undefined;
  status?: string | undefined;
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

export function useLists(boardId: string, loopId: string) {
  return useQuery({
    queryKey: keys.lists(boardId, loopId),
    queryFn: () => api.listLists(boardId, loopId),
    enabled: Boolean(boardId && loopId),
  });
}

export function useListCards(boardId: string, loopId: string, listId: string, limit: number) {
  return useQuery({
    queryKey: keys.listCards(boardId, loopId, listId, limit),
    queryFn: () => api.listCards(boardId, loopId, { list_id: listId, limit }),
    enabled: Boolean(boardId && loopId && listId),
  });
}

export function useLoops(boardId: string, includeCompleted = false) {
  return useQuery({
    queryKey: keys.loops(boardId, includeCompleted),
    queryFn: () => api.listLoops(boardId, { include_completed: includeCompleted }),
    enabled: Boolean(boardId),
  });
}

export function useLoop(boardId: string, loopId: string) {
  return useQuery({
    queryKey: keys.loop(boardId, loopId),
    queryFn: () => api.getLoop(boardId, loopId),
    enabled: Boolean(boardId && loopId),
  });
}

export function useLoopDocuments(boardId: string, loopId: string) {
  return useQuery({
    queryKey: keys.loopDocuments(boardId, loopId),
    queryFn: () => api.getLoopDocuments(boardId, loopId),
    enabled: Boolean(boardId && loopId),
  });
}

export function useLoopPlan(boardId: string, loopId: string) {
  return useQuery({
    queryKey: keys.loopPlan(boardId, loopId),
    queryFn: () => api.getLoopPlan(boardId, loopId),
    enabled: Boolean(boardId && loopId),
  });
}

export function useLoopAgents(boardId: string, loopId: string) {
  return useQuery({
    queryKey: ["loop-agents", boardId, loopId],
    queryFn: () => api.getLoopAgents(boardId, loopId),
  });
}

export function useReadiness(boardId: string, loopId: string) {
  return useQuery({
    queryKey: keys.readiness(boardId, loopId),
    queryFn: () => api.getReadiness(boardId, loopId),
    enabled: Boolean(boardId && loopId),
  });
}

export function useQaCycle(boardId: string, loopId: string, enabled = true) {
  return useQuery({
    queryKey: keys.qa(boardId, loopId),
    queryFn: () => api.getQaCycle(boardId, loopId),
    enabled: Boolean(boardId && loopId) && enabled,
  });
}

export function useHistory(
  boardId: string,
  params: {
    q?: string | undefined;
    source_kind?: string | undefined;
    qa_status?: string | undefined;
  },
) {
  return useQuery({
    queryKey: keys.history(boardId, params),
    queryFn: () => api.searchHistory(boardId, { ...params, limit: 100 }),
    enabled: Boolean(boardId),
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
