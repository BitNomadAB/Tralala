import { Bot, GitBranch } from "lucide-react";
import { Badge } from "@/components/ui/badge";

/** What this board is about: the code it may read and the agents that may work on it. */
export function BoardContext({
  agentIds,
  repositoryIds,
  agents,
  repositories,
}: {
  agentIds: string[];
  repositoryIds: string[];
  agents: { id: string; name: string }[];
  repositories: { id: string; name: string }[];
}) {
  const agentNames = agentIds
    .map((id) => agents.find((agent) => agent.id === id)?.name)
    .filter((name): name is string => Boolean(name));
  const repositoryNames = repositoryIds
    .map((id) => repositories.find((repository) => repository.id === id)?.name)
    .filter((name): name is string => Boolean(name));

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="flex items-center gap-1 text-[var(--muted-foreground)]">
        <GitBranch size={11} /> Code
      </span>
      {repositoryNames.length > 0 ? (
        repositoryNames.map((name) => (
          <Badge key={name} tone="neutral">
            {name}
          </Badge>
        ))
      ) : (
        <span className="text-[var(--muted-foreground)]">none selected</span>
      )}
      <span className="ml-2 flex items-center gap-1 text-[var(--muted-foreground)]">
        <Bot size={11} /> Agents
      </span>
      {agentNames.length > 0 ? (
        agentNames.map((name) => (
          <Badge key={name} tone="brand">
            {name}
          </Badge>
        ))
      ) : (
        <span className="text-[var(--muted-foreground)]">any enabled agent</span>
      )}
    </div>
  );
}
