import { Lock, PenLine, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import type { GenerationCandidates } from "@/lib/boardAgents";
import type { PlanScope, PlanTab } from "./loopUi";

/**
 * The Info / Analysis / RoadMap tabs, with the switch between the brief for people and the technical
 * version for AI, and the generation controls.
 */
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
  onRewrite,
  rewriteBlocked = null,
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
  /** Have a board agent write the brief for people again; absent for a reader. */
  onRewrite?: (() => void) | undefined;
  /** Why the rewrite cannot start, shown beside the button; null when it can. */
  rewriteBlocked?: string | null;
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
        <div role="group" aria-label="Version" className="flex gap-1">
          {(
            [
              ["For people", false],
              ["For AI", true],
            ] as const
          ).map(([label, forAi]) => (
            <Button
              key={label}
              size="sm"
              variant={technical === forAi ? "outline" : "ghost"}
              aria-pressed={technical === forAi}
              onClick={technical === forAi ? undefined : onToggleTechnical}
            >
              {label}
            </Button>
          ))}
        </div>
      ) : null}
      {tab !== "info" && !technical && onRewrite ? (
        <span className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            disabled={rewriteBlocked !== null}
            aria-describedby={rewriteBlocked ? "rewrite-blocked" : undefined}
            onClick={onRewrite}
          >
            <PenLine size={14} /> Rewrite for people
          </Button>
          {rewriteBlocked ? (
            <span id="rewrite-blocked" className="text-[11px] text-[var(--muted-foreground)]">
              {rewriteBlocked}
            </span>
          ) : null}
        </span>
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
