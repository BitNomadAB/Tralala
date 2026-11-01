import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Gauge, Pause, Play, Square, Timer } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import type { Discussion, DiscussionRunSummary } from "@/lib/types";

const RUN_TONES: Record<string, BadgeTone> = {
  running: "brand",
  paused: "warning",
  stopped: "danger",
  completed: "success",
  failed: "danger",
  budget_exhausted: "warning",
  no_progress: "warning",
};

const ROUND_TONES: Record<string, BadgeTone> = {
  completed: "neutral",
  paused: "warning",
  stopped: "danger",
  failed: "danger",
  budget_exhausted: "warning",
  no_progress: "warning",
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function optionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function RunPanel({
  boardId,
  discussion,
  onChanged,
}: {
  boardId: string;
  discussion: Discussion;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [planning, setPlanning] = useState(false);
  const [rounds, setRounds] = useState(String(discussion.max_rounds));
  const [autonomous, setAutonomous] = useState(discussion.mode === "autonomous");
  const [tokenBudget, setTokenBudget] = useState("");
  const [timeBudget, setTimeBudget] = useState("");

  const activeRun = discussion.active_run ?? null;
  const latestRun = discussion.runs?.[0] ?? activeRun;
  const runState = discussion.run_state ?? "idle";
  const closed = ["approved", "vetoed", "cancelled"].includes(discussion.status);
  const busy = runState === "running";
  const paused = runState === "paused";

  const report = (result: DiscussionRunSummary) => {
    onChanged();
    const failureText = result.failures.length
      ? result.failures.map((failure) => `${failure.agent}: ${failure.error}`).join(", ")
      : undefined;
    if (result.pending) {
      toast.push({ title: "Run started", description: failureText, variant: "success" });
      return;
    }
    const title =
      result.run_status === "completed"
        ? `Run finished (${result.answers} answers)`
        : `Run ${result.run_status}${result.stop_reason ? ` — ${result.stop_reason}` : ""}`;
    toast.push({
      title,
      description: failureText,
      variant: result.run_status === "completed" && !failureText ? "success" : "error",
    });
  };

  const failureMessage = (error: unknown) =>
    error instanceof ApiError ? error.message : undefined;

  const startMutation = useMutation({
    mutationFn: (input: {
      rounds?: number;
      autonomous: boolean;
      token_budget?: number;
      time_budget_seconds?: number;
    }) => api.startDiscussion(boardId, discussion.id, input),
    onSuccess: (result) => {
      setPlanning(false);
      report(result);
    },
    onError: (error) =>
      toast.push({
        title: "Could not start the run",
        description: failureMessage(error),
        variant: "error",
      }),
  });

  const controlMutation = useMutation({
    mutationFn: (action: "pause" | "resume" | "stop") =>
      api.controlDiscussionRun(boardId, discussion.id, String(activeRun?.id), action),
    onSuccess: (result, action) => {
      onChanged();
      toast.push({
        title:
          action === "pause"
            ? "Run paused"
            : action === "resume"
              ? "Run resumed"
              : "Run stopped",
        description: result.stop_reason ?? undefined,
        variant: action === "stop" ? "error" : "success",
      });
    },
    onError: (error) =>
      toast.push({
        title: "Could not update the run",
        description: failureMessage(error),
        variant: "error",
      }),
  });

  return (
    <div className="mt-2 rounded-lg border border-[var(--border)] p-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
        <span className="font-medium text-[var(--foreground)]">Run control</span>
        <Badge tone={RUN_TONES[runState] ?? "neutral"}>{runState}</Badge>
        <span data-testid="round-counter">
          Rounds {discussion.round_count}
          {latestRun ? ` · this run ${latestRun.rounds_completed}/${latestRun.rounds_requested}` : ""}
        </span>
        <span className="inline-flex items-center gap-1">
          <Gauge size={12} /> {discussion.tokens_used} tokens
          {activeRun?.token_budget ? ` / ${activeRun.token_budget}` : ""}
        </span>
        <span className="inline-flex items-center gap-1">
          <Timer size={12} /> {formatDuration(discussion.elapsed_ms)}
        </span>
        {latestRun?.stop_reason ? <span>stopped: {latestRun.stop_reason}</span> : null}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={closed || busy || paused}
          onClick={() => startMutation.mutate({ rounds: 1, autonomous: false })}
        >
          <Play size={14} />
          Run round
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={closed || busy || paused}
          onClick={() => setPlanning(true)}
        >
          Run autonomously
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={!busy || controlMutation.isPending}
          onClick={() => controlMutation.mutate("pause")}
        >
          <Pause size={14} /> Pause run
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={!paused || controlMutation.isPending}
          onClick={() => controlMutation.mutate("resume")}
        >
          <Play size={14} /> Resume run
        </Button>
        <Button
          size="sm"
          variant="danger"
          disabled={!(busy || paused) || controlMutation.isPending}
          onClick={() => controlMutation.mutate("stop")}
        >
          <Square size={14} /> Stop run
        </Button>
      </div>

      {latestRun && latestRun.rounds.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-1 text-[11px] text-[var(--muted-foreground)]">
          {latestRun.rounds.map((round) => (
            <li
              key={round.id}
              className="flex flex-wrap items-center gap-2 rounded border border-[var(--border)] px-1.5 py-0.5"
            >
              <span className="font-medium text-[var(--foreground)]">R{round.round_number}</span>
              <Badge tone={ROUND_TONES[round.status] ?? "neutral"}>{round.status}</Badge>
              <span>{round.answers} answers</span>
              {round.repeats ? <span>{round.repeats} repeated</span> : null}
              {round.failures ? <span>{round.failures} failed</span> : null}
              <span>{round.tokens_used} tokens</span>
              <span>{formatDuration(round.elapsed_ms)}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <Dialog open={planning} onOpenChange={setPlanning}>
        <DialogContent
          title="Run discussion"
          description="The loop stops at consensus, when rounds, tokens or time run out, or when answers repeat."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              startMutation.mutate({
                rounds: optionalNumber(rounds),
                autonomous,
                token_budget: optionalNumber(tokenBudget),
                time_budget_seconds: optionalNumber(timeBudget),
              });
            }}
          >
            <Field label="Rounds" htmlFor="run-rounds" hint={`Thread allows ${discussion.max_rounds}.`}>
              <Input
                id="run-rounds"
                type="number"
                min={1}
                max={10}
                value={rounds}
                onChange={(event) => setRounds(event.target.value)}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autonomous}
                onChange={(event) => setAutonomous(event.target.checked)}
              />
              Keep running autonomously
            </label>
            <Field label="Token budget (optional)" htmlFor="run-token-budget">
              <Input
                id="run-token-budget"
                type="number"
                min={0}
                value={tokenBudget}
                onChange={(event) => setTokenBudget(event.target.value)}
                placeholder="No limit"
              />
            </Field>
            <Field label="Time budget in seconds (optional)" htmlFor="run-time-budget">
              <Input
                id="run-time-budget"
                type="number"
                min={0}
                value={timeBudget}
                onChange={(event) => setTimeBudget(event.target.value)}
                placeholder="No limit"
              />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setPlanning(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={startMutation.isPending}>
                {startMutation.isPending ? "Starting…" : "Start run"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
