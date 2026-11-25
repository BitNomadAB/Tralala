import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { HeldButton } from "@/components/ui/held-button";
import { Select } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { useQaCycle } from "@/lib/queries";
import type { Loop } from "@/lib/types";
import { NO_SCENARIOS, qaRefusal } from "./qaRefusal";
import { QaScenarioResults, type ResultStatus } from "./QaScenarioResults";

/**
 * "2. Quality assurance" of the completion dialog: the cycle's scenarios with the result a person
 * records for each, the waiver for one that does not apply, and the person's decision on QA.
 *
 * A decision the server will refuse is not left to a toast. A cycle without scenarios can never be
 * accepted, so Accept QA and complete is held and the sentence beside the scenarios says why and
 * names the way to close the Loop without them. A refusal for unresolved scenarios is listed in the
 * section, one line a scenario, and stays until the next attempt.
 */
export function QaDecision({
  boardId,
  loop,
  qa,
  isHuman,
  note,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  qa: NonNullable<Loop["qa"]>;
  isHuman: boolean;
  /** The dialog's optional note, recorded with the decision. */
  note: string;
  onChanged: () => void;
}) {
  const toast = useToast();
  const qaQuery = useQaCycle(boardId, loop.id);
  const [draftResults, setDraftResults] = useState<Record<string, ResultStatus>>({});
  const [notApplicable, setNotApplicable] = useState<string[]>([]);
  const [refusal, setRefusal] = useState<string[] | null>(null);
  const noScenariosId = useId();

  const scenarios = useMemo(() => {
    const instructions = qaQuery.data?.human_instructions as
      { scenarios?: { id: string; title: string }[] } | undefined;
    return instructions?.scenarios ?? [];
  }, [qaQuery.data]);
  // Known to have none, not merely still being read.
  const noScenarios = qaQuery.data !== undefined && scenarios.length === 0;

  const submitResults = useMutation({
    mutationFn: () =>
      api.submitQaResults(boardId, loop.id, {
        results: Object.entries(draftResults).map(([scenarioId, status]) => ({
          scenario_id: scenarioId,
          status,
          reason: status === "not_applicable" ? "Not applicable" : "",
          evidence: "",
        })),
      }),
    onSuccess: () => {
      onChanged();
      toast.push({ title: "QA results recorded", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not record results",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  const decide = useMutation({
    mutationFn: (decision: "accepted" | "rejected") =>
      api.decideQa(boardId, loop.id, {
        version: loop.version,
        cycle_id: qaQuery.data?.id ?? "",
        decision,
        not_applicable_approvals: notApplicable,
        note,
      }),
    onMutate: () => {
      setRefusal(null);
    },
    onSuccess: () => {
      onChanged();
      toast.push({ title: "QA decision recorded", variant: "success" });
    },
    onError: (error) => {
      const titles = new Map(scenarios.map((scenario) => [scenario.id, scenario.title]));
      const lines = qaRefusal(error, titles);
      setRefusal(lines);
      toast.push({
        title: "Could not record the decision",
        description:
          lines.length === 1
            ? (lines[0] ?? "")
            : `${String(lines.length)} scenarios are unresolved; the dialog lists them.`,
        variant: "error",
      });
    },
  });

  return (
    <section className="flex flex-col gap-2 border-t border-[var(--border)] pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-medium">2. Quality assurance</h2>
        <Badge tone={qa.status === "accepted" ? "success" : "warning"}>
          cycle {qa.cycle_number} · {qa.status.replace("_", " ")}
        </Badge>
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">
        One QA Task in the Kanban carries both an agent view and a human view built from the same
        scenario ids.
      </p>
      <QaScenarioResults
        scenarios={scenarios}
        results={draftResults}
        onResultChange={(scenarioId, status) =>
          setDraftResults((current) => ({ ...current, [scenarioId]: status }))
        }
      />
      {noScenarios ? (
        <p id={noScenariosId} className="m-0 text-xs text-[var(--foreground)]">
          {NO_SCENARIOS}
        </p>
      ) : null}
      {refusal ? (
        <div
          role="alert"
          className="grid gap-1 rounded-lg border border-[var(--destructive)] p-2 text-xs"
        >
          <p className="m-0 font-medium">QA was not accepted:</p>
          <ul className="m-0 grid list-disc gap-0.5 pl-4">
            {refusal.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <HeldButton
          variant="outline"
          held={submitResults.isPending}
          disabled={Object.keys(draftResults).length === 0}
          onClick={() => submitResults.mutate()}
        >
          Record results
        </HeldButton>
        <Select
          aria-label="Scenarios approved as not applicable"
          className="h-8 w-auto"
          value={notApplicable[0] ?? ""}
          onChange={(event) => setNotApplicable(event.target.value ? [event.target.value] : [])}
        >
          <option value="">No not-applicable waivers</option>
          {scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              Waive {scenario.id}
            </option>
          ))}
        </Select>
        <HeldButton
          variant="outline"
          held={decide.isPending}
          disabled={!isHuman}
          onClick={() => decide.mutate("rejected")}
        >
          <XCircle size={14} /> Reject QA
        </HeldButton>
        <HeldButton
          held={decide.isPending || noScenarios}
          reasonId={noScenarios ? noScenariosId : undefined}
          disabled={!isHuman}
          onClick={() => decide.mutate("accepted")}
        >
          <CheckCircle2 size={14} /> Accept QA and complete
        </HeldButton>
      </div>
    </section>
  );
}
