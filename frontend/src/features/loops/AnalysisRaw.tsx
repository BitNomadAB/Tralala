import { SectionHeader } from "@/components/ui/section";
import { findingsOf } from "./briefs";

const BLOCK =
  "m-0 whitespace-pre-wrap break-words rounded-md border border-[var(--border)] bg-[var(--surface)] p-3 font-mono text-xs";

/**
 * Raw text of an analysis: the findings as the technical analysis states them (id, category,
 * title, the detail for engineers and the plain words), then the whole technical revision as JSON.
 * AI text, shown as it is and unstyled on purpose.
 */
export function AnalysisRaw({ technical }: { technical: unknown }) {
  const findings = findingsOf(technical);
  return (
    <div className="grid gap-[22px]">
      <section>
        <SectionHeader title="Findings" count={findings.length} />
        {findings.length > 0 ? (
          <ul className="m-0 grid list-none gap-3 p-0 text-[13px]">
            {findings.map((finding, index) => (
              <li key={`${index}-${finding.id}`} className="grid gap-0.5">
                <span className="font-mono text-xs text-[var(--muted-foreground)]">
                  {finding.id} · {finding.category}
                </span>
                <span className="font-medium">{finding.title}</span>
                {finding.technical_detail ? <span>{finding.technical_detail}</span> : null}
                {finding.plain_language ? (
                  <span className="text-[var(--muted-foreground)]">{finding.plain_language}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-[13px] text-[var(--foreground-faint)]">
            The technical analysis has no findings.
          </p>
        )}
      </section>
      <section>
        <SectionHeader title="Technical analysis (JSON)" />
        <pre className={BLOCK}>{JSON.stringify(technical ?? null, null, 2)}</pre>
      </section>
    </div>
  );
}
