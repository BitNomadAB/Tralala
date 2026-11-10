import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useEffectEvent, useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { GenerationPurpose, GenerationRun } from "@/lib/types";
import type { PlanTab } from "./loopUi";

/** A purpose to run, or one with what the person adds to it (a RoadMap written again). */
export type GenerationAsk =
  GenerationPurpose | { purpose: GenerationPurpose; instructions: string };

const inFlight = (run: Pick<GenerationRun, "status">) =>
  run.status === "queued" || run.status === "running";

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
    mutationFn: (ask: GenerationAsk) => {
      const { purpose, instructions } =
        typeof ask === "string" ? { purpose: ask, instructions: "" } : ask;
      return api.startGeneration(boardId, loopId, purpose, agentId || undefined, instructions);
    },
    onSuccess: (run) => {
      setRunId(run.id);
      setFailure(null);
      onStarted();
      invalidate();
      toast.push({
        title: "Generation started",
        description: "Following the run…",
        variant: "success",
      });
    },
    onError: (error) => {
      toast.push({
        title: "Generation unavailable",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  // Follow the run instead of asking the person to reload: generation answers in the background.
  const runQuery = useQuery({
    queryKey: ["generation-run", loopId, runId],
    queryFn: () => api.getGenerationRun(boardId, loopId, String(runId)),
    enabled: Boolean(runId),
    refetchInterval: (query) => (query.state.data && inFlight(query.state.data) ? 1500 : false),
  });
  const run = runId ? runQuery.data : undefined;
  const runFinished = run ? ["completed", "failed", "cancelled"].includes(run.status) : false;

  // A failed run used to exist only as a toast that scrolled away, so "I pressed Generate and
  // nothing happened" was the honest description of a failed provider call. The last run for the
  // purpose stays on screen instead, with whatever the provider said. The Info tab reads the list
  // too: a save there asks first while any run of the Loop is in flight, including one started
  // before the dialog opened, so the list is followed for as long as it shows one.
  const runsQuery = useQuery({
    queryKey: keys.generationRuns(boardId, loopId),
    queryFn: () => api.listGenerationRuns(boardId, loopId),
    refetchInterval: (query) =>
      (runId && !runFinished) || query.state.data?.some(inFlight) ? 1500 : false,
  });
  const purposeRuns = (runsQuery.data ?? []).filter((entry) => entry.purpose === tab);
  const lastRun = purposeRuns.at(0);
  // A board agent writes the brief for people of a new analysis or RoadMap in a run of its own,
  // started by the server; the list follows it, and its end brings the written view in.
  const forPeople = tab === "roadmap" ? "roadmap_human" : "analysis_human";
  const writingForPeople =
    tab !== "info" &&
    (runsQuery.data ?? []).some((entry) => entry.purpose === forPeople && inFlight(entry));
  const [wasWriting, setWasWriting] = useState(false);
  const [writtenAt, setWrittenAt] = useState(0);
  if (writingForPeople !== wasWriting) {
    setWasWriting(writingForPeople);
    if (!writingForPeople) setWrittenAt((count) => count + 1);
  }
  const refreshWritten = useEffectEvent(() => invalidate());
  useEffect(() => {
    if (writtenAt > 0) refreshWritten();
  }, [writtenAt]);

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
    const cancelled = finished.status === "cancelled";
    toast.push({
      title: cancelled ? "Generation cancelled" : "Generation failed",
      // A cancelled run records no message, and "the provider did not answer" was not why it ended.
      description:
        finished.error_message ??
        (cancelled
          ? "The run was stopped before its result was used."
          : "The provider did not return a usable answer."),
      variant: "error",
    });
  });

  useEffect(() => {
    if (finishedRun) announceFinishedRun(finishedRun);
  }, [finishedRun]);

  const generating = Boolean(runId) && !runFinished;
  // A failed run keeps its panel until dismissed, so the step and the provider's answer stay put.
  const visibleRun = generating ? run : tab === "info" ? undefined : failure;

  const cancelRun = useMutation({
    mutationFn: (id: string) => api.cancelGenerationRun(boardId, loopId, id),
    onSuccess: invalidate,
    onError: (error) => {
      toast.push({
        title: "Could not cancel the run",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  return {
    generate,
    /** A run is being followed; the agent choice is locked until it finishes. */
    following: Boolean(runId),
    generating,
    visibleRun,
    /** The run of any purpose a save of Info would leave without a result, or null when none is. */
    activeRunId: generating ? runId : (runsQuery.data?.find(inFlight)?.id ?? null),
    cancelRun,
    lastRun,
    lastRunLoading: runsQuery.isLoading,
    /** A board agent is writing the open scope's brief for people; it is not approved meanwhile. */
    writingForPeople,
    dismissFailure: () => {
      setFailure(null);
    },
  };
}
