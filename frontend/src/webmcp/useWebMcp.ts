import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthProvider";
import type { BoardList, Card } from "@/lib/types";
import { getModelContext } from "./capability";
import { createRegistry } from "./registry";
import { cardTools, dashboardTools, loopTools, type McpTool } from "./tools";

function useContextualTools(tools: McpTool[] | null): void {
  const { actor } = useAuth();
  const actorType = actor?.type;
  const actorScopes = actor?.scopes.join(",") ?? "";

  useEffect(() => {
    if (!tools) return;
    const context = getModelContext();
    if (!context) return;
    const allowed = tools.filter((tool) => {
      if (!tool.requiredScope) return true;
      if (actorType === "user") return true;
      return actorScopes.split(",").includes(tool.requiredScope);
    });
    if (allowed.length === 0) return;
    const registry = createRegistry(context);
    void registry.register(allowed.map(({ requiredScope, ...tool }) => tool));
    return () => registry.dispose();
  }, [tools, actorType, actorScopes]);
}

export function useDashboardTools(): void {
  const navigate = useNavigate();
  const tools = useMemo(() => dashboardTools({ onOpenBoard: (id) => navigate(`/boards/${id}`) }), [navigate]);
  useContextualTools(tools);
}

export function useLoopTools(options: {
  boardId: string;
  loopId: string;
  loopName: string;
  lists: BoardList[];
  cardsByList: Record<string, Card[]>;
  onOpenCard: (cardId: string) => void;
}): void {
  const { boardId, loopId, loopName, lists, cardsByList, onOpenCard } = options;
  // Only counts feed the overview tool, so re-registering on a transport-level change is
  // avoided by keying on the loop shape instead of object identity.
  const shape = `${lists.map((list) => `${list.id}:${list.name}:${cardsByList[list.id]?.length ?? 0}`).join("|")}`;
  const tools = useMemo(
    () => loopTools({ boardId, loopId, loopName, lists, cardsByList, onOpenCard }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [boardId, loopId, loopName, shape, onOpenCard],
  );
  useContextualTools(tools);
}

export function useCardTools(options: {
  boardId: string;
  loopId: string;
  cardId: string;
  onOpen: () => void;
  onClose: () => void;
}): void {
  const { boardId, loopId, cardId, onClose } = options;
  const tools = useMemo(
    () => cardTools({ boardId, loopId, cardId, onClose }),
    [boardId, loopId, cardId, onClose],
  );
  useContextualTools(tools);
}

export { useContextualTools };
