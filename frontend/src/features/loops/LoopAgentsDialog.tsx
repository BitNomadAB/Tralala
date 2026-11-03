import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { generationAgents } from "@/lib/boardAgents";
import { describeError } from "@/lib/describeError";
import { useAgents, useBoard, useLoopAgents } from "@/lib/queries";
import type { Loop, LoopAgentPreferences } from "@/lib/types";

const PURPOSES = [
  { key: "analysis_agent_id", purpose: "analysis", label: "Analysis" },
  { key: "roadmap_agent_id", purpose: "roadmap", label: "RoadMap" },
  { key: "qa_agent_id", purpose: "qa", label: "QA instructions" },
] as const;

type PurposeKey = (typeof PURPOSES)[number]["key"];

/** "" is "Board default" in every select, and is sent as null. */
const NO_CHOICE: Record<PurposeKey, string> = {
  analysis_agent_id: "",
  roadmap_agent_id: "",
  qa_agent_id: "",
};

/**
 * Which agent this Loop prefers per purpose. A stored choice only fills in the default of the next
 * run; the run dialog can still deviate, and the server still refuses an agent the board dropped.
 */
export function LoopAgentsDialog({
  boardId,
  loop,
  open,
  onClose,
}: {
  boardId: string;
  loop: Loop;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const boardQuery = useBoard(boardId);
  const agentsQuery = useAgents();
  const preferencesQuery = useLoopAgents(boardId, loop.id);
  const [draft, setDraft] = useState<Record<PurposeKey, string>>(NO_CHOICE);
  const [draftSource, setDraftSource] = useState<LoopAgentPreferences | undefined>(undefined);

  const boardAgents = useMemo(
    () => generationAgents(agentsQuery.data ?? [], boardQuery.data?.agent_ids).agents,
    [agentsQuery.data, boardQuery.data?.agent_ids],
  );

  // The draft follows each new copy of the stored choice; set while rendering, not in an effect.
  const stored = preferencesQuery.data;
  if (stored && stored !== draftSource) {
    setDraftSource(stored);
    setDraft({
      analysis_agent_id: stored.analysis_agent_id ?? "",
      roadmap_agent_id: stored.roadmap_agent_id ?? "",
      qa_agent_id: stored.qa_agent_id ?? "",
    });
  }

  const save = useMutation({
    mutationFn: () =>
      api.setLoopAgents(boardId, loop.id, {
        analysis_agent_id: draft.analysis_agent_id || null,
        roadmap_agent_id: draft.roadmap_agent_id || null,
        qa_agent_id: draft.qa_agent_id || null,
      } satisfies Partial<LoopAgentPreferences>),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["loop-agents", boardId, loop.id] });
      toast.push({ title: "Loop agents saved", variant: "success" });
      onClose();
    },
    onError: (error) => {
      toast.push({
        title: "Could not save",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent
        title={`${loop.key} agents`}
        description="Which agent this Loop uses by default for each generation. Board members only."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          {PURPOSES.map((entry) => (
            <Field key={entry.key} label={entry.label} htmlFor={`loop-agent-${entry.purpose}`}>
              <Select
                id={`loop-agent-${entry.purpose}`}
                value={draft[entry.key]}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, [entry.key]: event.target.value }))
                }
              >
                <option value="">Board default</option>
                {boardAgents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                    {agent.model ? ` · ${agent.model}` : ""}
                  </option>
                ))}
              </Select>
            </Field>
          ))}
          {boardAgents.length === 0 ? (
            <p className="text-xs text-[var(--warning)]">
              This board lists no agent that can generate. Pick agents on the board first.
            </p>
          ) : (
            <p className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
              <Bot size={11} /> Only agents selected on the board are offered here.
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={save.isPending}>
              Save agents
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
