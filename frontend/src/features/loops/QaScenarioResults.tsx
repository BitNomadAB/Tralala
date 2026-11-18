import { Select } from "@/components/ui/input";

export type ResultStatus = "passed" | "failed" | "blocked" | "not_run" | "not_applicable";

const RESULT_OPTIONS: { value: ResultStatus; label: string }[] = [
  { value: "passed", label: "Passed" },
  { value: "failed", label: "Failed" },
  { value: "blocked", label: "Blocked" },
  { value: "not_run", label: "Not run" },
  { value: "not_applicable", label: "Not applicable" },
];

/** The QA scenarios of the Loop's cycle, each with the result a person records for it. */
export function QaScenarioResults({
  scenarios,
  results,
  onResultChange,
}: {
  scenarios: readonly { id: string; title: string }[];
  results: Readonly<Record<string, ResultStatus>>;
  onResultChange: (scenarioId: string, status: ResultStatus) => void;
}) {
  if (scenarios.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-[var(--border)] p-2 text-xs text-[var(--muted-foreground)]">
        No QA instructions yet. Generate them with a configured agent, or supply a scenario set
        through the API.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {scenarios.map((scenario) => (
        <li
          key={scenario.id}
          className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] px-2 py-1.5"
        >
          <span className="font-mono text-xs text-[var(--muted-foreground)]">{scenario.id}</span>
          <span className="text-sm">{scenario.title}</span>
          <Select
            className="ml-auto h-7 w-auto"
            aria-label={`Result for ${scenario.id}`}
            value={results[scenario.id] ?? ""}
            onChange={(event) => onResultChange(scenario.id, event.target.value as ResultStatus)}
          >
            <option value="">Not recorded</option>
            {RESULT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </li>
      ))}
    </ul>
  );
}
