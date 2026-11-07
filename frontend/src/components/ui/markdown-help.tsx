import { renderMarkdown } from "@/lib/markdown";
import { FORMATTING_EXAMPLES, type FormattingExample } from "./markdownExamples";

const examples: [string, FormattingExample][] = Object.entries(FORMATTING_EXAMPLES);

/** "How to format": what to type and, rendered by the same renderer, what it gives. */
export function MarkdownHelp() {
  return (
    <details className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs">
      <summary className="cursor-pointer font-medium">How to format</summary>
      <table className="mt-2 w-full border-collapse text-left">
        <thead>
          <tr className="text-[var(--muted-foreground)]">
            <th scope="col" className="w-1/2 pb-1 pr-3 font-medium">
              You write
            </th>
            <th scope="col" className="pb-1 font-medium">
              You get
            </th>
          </tr>
        </thead>
        <tbody>
          {examples.map(([name, example]) => (
            <tr
              key={name}
              data-example={name}
              className="border-t border-[var(--border)] align-top"
            >
              <td className="py-2 pr-3">
                <span className="block text-[var(--muted-foreground)]">{example.title}</span>
                <code className="block whitespace-pre-wrap font-mono">{example.syntax}</code>
              </td>
              <td className="py-2">
                <div className="prose-card" data-rendered>
                  {renderMarkdown(example.syntax)}
                </div>
                {example.note ? (
                  <p className="mt-1 text-[var(--muted-foreground)]">{example.note}</p>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
