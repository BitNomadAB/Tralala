import { Lock, PenLine, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeldButton } from "@/components/ui/held-button";
import { Select } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import type { GenerationCandidates } from "@/lib/boardAgents";
import type { PlanScope, PlanTab } from "./loopUi";

/**
 * The Info / Analysis / RoadMap switch, with the switch between the analysis brief for people and
 * the technical version for AI, and the generation controls. Each switch is a group of toggle
 * buttons (`aria-pressed`), so a screen reader hears which document is open, not only a colour
 * (WCAG 4.1.2). `generateId` names the Generate button, where the focus goes after a reset.
 * While `generateBusy` (a run starting or followed) Generate is unavailable but keeps the focus.
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
  generateBusy = false,
  onGenerate,
  onRewrite,
  rewriteBlocked = null,
  generateId,
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
  generateBusy?: boolean | undefined;
  onGenerate: (scope: PlanScope) => void;
  /** Have a board agent write the brief for people again; absent for a reader. */
  onRewrite?: (() => void) | undefined;
  /** Why the rewrite cannot start, shown beside the button; null when it can. */
  rewriteBlocked?: string | null;
  generateId?: string | undefined;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] pb-2">
      <div role="group" aria-label="Planning document" className="flex flex-wrap gap-2">
        {(["info", "analysis", "roadmap"] as PlanTab[]).map((entry) => (
          <Button
            key={entry}
            size="sm"
            variant={tab === entry ? "primary" : "ghost"}
            aria-pressed={tab === entry}
            onClick={() => onTabChange(entry)}
          >
            {entry === "info" ? "Info" : entry === "analysis" ? "Analysis" : "RoadMap"}
          </Button>
        ))}
      </div>
      {/* The RoadMap's review has its own For you | Raw text switch. */}
      {tab === "analysis" ? (
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
        <ReasonButton size="sm" variant="ghost" disabledReason={rewriteBlocked} onClick={onRewrite}>
          <PenLine size={14} /> Rewrite for people
        </ReasonButton>
      ) : null}
      {tab !== "info" ? (
        <label className="ml-auto flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
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
        <HeldButton
          id={generateId}
          size="sm"
          variant="outline"
          held={generateBusy}
          aria-busy={generating}
          data-generating={generating ? "true" : undefined}
          // The pulse and its glow only where motion is welcome (WCAG 2.2.2); under reduced motion
          // the running state is the steady ring and the "Generating…" text.
          className={
            generating
              ? "motion-safe:animate-pulse border-[var(--primary)] text-[var(--primary)] motion-safe:shadow-[0_0_22px_3px_var(--primary)] ring-2 ring-[var(--primary)] disabled:opacity-100 aria-disabled:opacity-100"
              : undefined
          }
          disabled={generateDisabled}
          onClick={() => onGenerate(tab)}
        >
          {generating ? <Lock size={14} /> : <Sparkles size={14} />}{" "}
          {generating ? "Generating…" : `Generate ${tab === "analysis" ? "analysis" : "RoadMap"}`}
        </HeldButton>
      ) : null}
    </div>
  );
}
