import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useEffectEvent, useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { GenerationRun } from "@/lib/types";
import { errorText, type PlanScope, type PlanTab } from "./loopUi";

/**
 * Starts a generation run for the open scope and follows it until it finishes, keeping a failed run
 * on screen until it is dismissed.
 */
export function useGenerationRun({
  boardId,
  loopId,
  tab,
  agentId,
  invalidate,
  onStarted,
}: {
  boardId: string;
  loopId: string;
  tab: PlanTab;
  agentId: string;
  invalidate: () => void;
  onStarted: () => void;
}) {
  const toast = useToast();
  const [runId, setRunId] = useState<string | null>(null);
  const [failure, setFailure] = useState<GenerationRun | null>(null);

  const generate = useMutation({
    mutationFn: (purpose: PlanScope) =>
      api.startGeneration(boardId, loopId, purpose, agentId || undefined),
    onSuccess: (run) => {
      setRunId(run.id);
      setFailure(null);
      onStarted();
      invalidate();
      toast.push({
        title: "Generation started",
        description: "Following the run?",
        variant: "success",
      });
    },
    onError: (error) => {
      toast.push({
        title: "Generation unavailable",
        description: errorText(error),
        variant: "error",
      });
    },
  });

  // Follow the run instead of asking the person to reload: generation answers in the background.
  const runQuery = useQuery({
    queryKey: ["generation-run", loopId, runId],
    queryFn: () => api.getGenerationRun(boardId, loopId, String(runId)),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 1500 : false;
    },
  });
  const run = runId ? runQuery.data : undefined;
  const runFinished = run ? ["completed", "failed", "cancelled"].includes(run.status) : false;

  // A failed run used to exist only as a toast that scrolled away, so "I pressed Generate and
  // nothing happened" was the honest description of a failed provider call. The last run for the
  // purpose stays on screen instead, with whatever the provider said.
  const runsQuery = useQuery({
    queryKey: keys.generationRuns(boardId, loopId),
    queryFn: () => api.listGenerationRuns(boardId, loopId),
    enabled: tab !== "info",
    refetchInterval: runId && !runFinished ? 1500 : false,
  });
  const purposeRuns = (runsQuery.data ?? []).filter((entry) => entry.purpose === tab);
  const lastRun = purposeRuns.at(0);

  // A finished run stops being followed, and a failed one keeps its step and the provider's answer on
  // screen instead of a toast that scrolls away. Both are state, so they are set while rendering
  // (React: "adjusting state when a prop changes"); the toast and the refresh are side effects and
  // wait for the effect below.
  const [finishedRun, setFinishedRun] = useState<GenerationRun | null>(null);
  if (run && runFinished) {
    setRunId(null);
    setFinishedRun(run);
    if (run.status === "completed") setFailure(null);
    else if (run.status === "failed") setFailure(run);
  }

  // Reads the latest toast and callbacks without re-announcing a run when they change.
  const announceFinishedRun = useEffectEvent((finished: GenerationRun) => {
    invalidate();
    if (finished.status === "completed") {
      toast.push({ title: "Draft ready for review", variant: "success" });
      return;
    }
    toast.push({
      title: finished.status === "cancelled" ? "Generation cancelled" : "Generation failed",
      description: finished.error_message ?? "The provider did not return a usable answer.",
      variant: "error",
    });
  });

  useEffect(() => {
    if (finishedRun) announceFinishedRun(finishedRun);
  }, [finishedRun]);

  const generating = Boolean(runId) && !runFinished;
  // A failed run keeps its panel until dismissed, so the step and the provider's answer stay put.
  const visibleRun = generating ? run : tab === "info" ? undefined : failure;

  return {
    generate,
    /** A run is being followed; the agent choice is locked until it finishes. */
    following: Boolean(runId),
    generating,
    visibleRun,
    lastRun,
    lastRunLoading: runsQuery.isLoading,
    dismissFailure: () => {
      setFailure(null);
    },
  };
}
