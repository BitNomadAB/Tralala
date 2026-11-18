import type { AgentTestResult } from "@/lib/types";

/**
 * The connection test's answer: a summary line, the models it reported and the raw result. Only
 * the summary is a live status, so a screen reader reads what the test found and not the whole raw
 * answer (WCAG 4.1.3); the raw answer is a box a keyboard can scroll (WCAG 2.1.1).
 */
export function AgentTestResultPanel({ result }: { result: AgentTestResult }) {
  return (
    <section
      aria-label="Connection test"
      className={`rounded-lg border p-2 text-xs ${
        result.ok
          ? "border-[var(--success,var(--primary))] text-[var(--foreground)]"
          : "border-[var(--destructive)] text-[var(--destructive)]"
      }`}
    >
      <div role="status" aria-label="Connection test result">
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
      </div>
      {result.models.length > 0 ? (
        <p className="mt-1 text-[var(--muted-foreground)]">
          {result.models.slice(0, 8).join(", ")}
          {result.models.length > 8 ? ` (+${result.models.length - 8} more)` : ""}
        </p>
      ) : null}
      {/* The raw answer, so the same block serves every provider and no field is lost. */}
      <pre
        role="group"
        aria-label="Raw test result"
        tabIndex={0}
        className="mt-2 max-h-64 overflow-auto rounded border border-[var(--border)] bg-[var(--surface-raised)] p-2 text-xs leading-snug"
      >
        {JSON.stringify(result, null, 2)}
      </pre>
    </section>
  );
}
