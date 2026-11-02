import { useQuery } from "@tanstack/react-query";
import { Bot, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { EXECUTABLE_CONNECTION_TYPES } from "@/lib/boardAgents";

/**
 * Checkbox list of the board profiles the installation knows about. A board that selects agents
 * narrows which one may generate its Loops; an empty selection keeps every enabled generator
 * available. Organisation profiles are not offered: their job is the whole installation.
 */
export function AgentPicker({
  selected,
  onChange,
  disabled,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}) {
  const agentsQuery = useQuery({
    queryKey: ["agents"],
    queryFn: () => api.listAgents(),
    staleTime: 60_000,
  });
  const all = agentsQuery.data ?? [];
  const agents = all.filter((agent) => agent.role_template_scope !== "organisation");
  const organisationCount = all.length - agents.length;

  if (agentsQuery.isLoading) {
    return <p className="text-xs text-[var(--muted-foreground)]">Loading agents…</p>;
  }
  if (agents.length === 0) {
    return (
      <p className="text-xs text-[var(--muted-foreground)]">
        No board agent is configured yet. An administrator adds one under Settings - Agents.
      </p>
    );
  }

  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        Agents
      </legend>
      <p className="text-xs text-[var(--muted-foreground)]">
        Who works on this board. A Loop may only generate on one of these; leave all unchecked to
        allow any enabled board profile.
        {organisationCount > 0
          ? ` ${organisationCount} organisation profile(s) work across every board and are not listed here.`
          : ""}
      </p>
      <div className="flex flex-col gap-1 rounded-lg border border-[var(--border)] p-2">
        {agents.map((agent) => {
          const canGenerate =
            agent.enabled && EXECUTABLE_CONNECTION_TYPES.includes(agent.connection_type);
          return (
            <label key={agent.id} className="flex flex-wrap items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selected.includes(agent.id)}
                disabled={disabled}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...selected, agent.id]
                      : selected.filter((id) => id !== agent.id),
                  )
                }
              />
              <Bot size={13} className="text-[var(--muted-foreground)]" />
              <span className="font-medium">{agent.name}</span>
              {agent.role_template_name ? (
                <span className="text-[11px] text-[var(--muted-foreground)]">
                  {agent.role_template_name}
                </span>
              ) : null}
              {canGenerate ? (
                <span className="flex items-center gap-1 text-[11px] text-[var(--muted-foreground)]">
                  <Sparkles size={11} />
                  {agent.model ?? "default model"}
                </span>
              ) : (
                <span className="text-[11px] text-[var(--warning)]">
                  {agent.enabled ? "cannot generate" : "disabled"}
                </span>
              )}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
