import type { AgentTestResult } from "@/lib/types";

/** The connection test's answer: a summary line, the models it reported and the raw result. */
export function AgentTestResultPanel({ result }: { result: AgentTestResult }) {
  return (
    <div
      role="status"
      aria-label="Connection test result"
      aria-live="polite"
      className={`rounded-lg border p-2 text-xs ${
        result.ok
          ? "border-[var(--success,var(--primary))] text-[var(--foreground)]"
          : "border-[var(--destructive)] text-[var(--destructive)]"
      }`}
    >
      <p className="font-medium">
        {result.status}
        {result.latency_ms !== null ? ` · ${result.latency_ms} ms` : ""}
      </p>
      <p>{result.message}</p>
      {result.completion ? (
        <p className="mt-1">
          Model call: {result.completion.status} · {result.completion.message}
        </p>
      ) : null}
      {result.models.length > 0 ? (
        <p className="mt-1 text-[var(--muted-foreground)]">
          {result.models.slice(0, 8).join(", ")}
          {result.models.length > 8 ? ` (+${result.models.length - 8} more)` : ""}
        </p>
      ) : null}
      {/* The raw answer, so the same block serves every provider and no field is lost. */}
      <pre className="mt-2 max-h-64 overflow-auto rounded border border-[var(--border)] bg-[var(--surface-raised)] p-2 text-[11px] leading-snug">
        {JSON.stringify(result, null, 2)}
      </pre>
    </div>
  );
}
