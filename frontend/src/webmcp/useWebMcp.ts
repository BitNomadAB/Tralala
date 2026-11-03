import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/useAuth";
import type { BoardList, Card } from "@/lib/types";
import { getModelContext } from "./capability";
import { createRegistry } from "./registry";
import { cardTools, dashboardTools, loopTools, type LoopColumn, type McpTool } from "./tools";

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

/**
 * The same array for as long as its content is the same, so it can be a memo dependency. The
 * previous value is kept in state and replaced while rendering (React: "storing information from
 * previous renders").
 */
function useStableValue(value: LoopColumn[]): LoopColumn[] {
  const key = JSON.stringify(value);
  const [stable, setStable] = useState({ key, value });
  if (stable.key !== key) {
    setStable({ key, value });
    return value;
  }
  return stable.value;
}

export function useDashboardTools(): void {
  const navigate = useNavigate();
  const tools = useMemo(
    () =>
      dashboardTools({
        onOpenBoard: (id) => {
          void navigate(`/boards/${id}`);
        },
      }),
    [navigate],
  );
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
  // Only the column summary feeds the overview tool, so the tools are rebuilt (and re-registered)
  // when that summary changes, not whenever the card queries hand back new arrays.
  const columns = useStableValue(
    lists.map((list) => ({
      id: list.id,
      name: list.name,
      card_count: (cardsByList[list.id] ?? []).length,
    })),
  );
  const tools = useMemo(
    () => loopTools({ boardId, loopId, loopName, columns, onOpenCard }),
    [boardId, loopId, loopName, columns, onOpenCard],
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
