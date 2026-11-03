import { Lock, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import type { GenerationCandidates } from "@/lib/boardAgents";
import type { PlanScope, PlanTab } from "./loopUi";

/** The Info / Analysis / RoadMap tabs, with the view toggle and the generation controls. */
export function LoopPlanTabs({
  tab,
  onTabChange,
  technical,
  onToggleTechnical,
  agentId,
  onAgentChange,
  candidates,
  savedAgentName,
  agentLocked,
  generating,
  generateDisabled,
  onGenerate,
}: {
  tab: PlanTab;
  onTabChange: (tab: PlanTab) => void;
  technical: boolean;
  onToggleTechnical: () => void;
  agentId: string;
  onAgentChange: (agentId: string) => void;
  candidates: GenerationCandidates;
  savedAgentName: string | undefined;
  agentLocked: boolean;
  generating: boolean;
  generateDisabled: boolean;
  onGenerate: (scope: PlanScope) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] pb-2">
      {(["info", "analysis", "roadmap"] as PlanTab[]).map((entry) => (
        <Button
          key={entry}
          size="sm"
          variant={tab === entry ? "primary" : "ghost"}
          onClick={() => onTabChange(entry)}
        >
          {entry === "info" ? "Info" : entry === "analysis" ? "Analysis" : "RoadMap"}
        </Button>
      ))}
      {tab !== "info" ? (
        <Button size="sm" variant="ghost" onClick={onToggleTechnical}>
          {technical ? "Human view" : "Technical view"}
        </Button>
      ) : null}
      {tab !== "info" ? (
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
          Agent
          <Select
            aria-label="Generation agent"
            className="w-52"
            value={agentId}
            onChange={(event) => onAgentChange(event.target.value)}
            disabled={agentLocked}
          >
            <option value="">
              {savedAgentName
                ? `Default (${savedAgentName})`
                : candidates.agents.length > 0
                  ? candidates.restrictedToBoard
                    ? "Default (board agent)"
                    : "Default (first by name)"
                  : candidates.restrictedToBoard
                    ? "No board agent can generate"
                    : "No agent configured"}
            </option>
            {candidates.agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
                {agent.model ? ` · ${agent.model}` : ""}
              </option>
            ))}
          </Select>
        </label>
      ) : null}
      {tab !== "info" ? (
        <Button
          size="sm"
          variant="outline"
          aria-busy={generating}
          data-generating={generating ? "true" : undefined}
          className={
            generating
              ? "animate-pulse border-[var(--primary)] text-[var(--primary)] shadow-[0_0_22px_3px_var(--primary)] ring-2 ring-[var(--primary)] disabled:opacity-100"
              : undefined
          }
          disabled={generateDisabled}
          onClick={() => onGenerate(tab)}
        >
          {generating ? <Lock size={14} /> : <Sparkles size={14} />}{" "}
          {generating ? "Generating…" : `Generate ${tab === "analysis" ? "analysis" : "RoadMap"}`}
        </Button>
      ) : null}
    </div>
  );
}
