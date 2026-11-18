import { renderMarkdown } from "@/lib/markdown";
import { FORMATTING_EXAMPLES, type FormattingExample } from "./markdownExamples";

const examples: [string, FormattingExample][] = Object.entries(FORMATTING_EXAMPLES);

/**
 * "How to format": what to type and, rendered by the same renderer, what it gives, with the
 * keyboard shortcut where the field has one.
 */
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
                {example.shortcut ? (
                  <span className="mt-1 block text-[var(--muted-foreground)]">
                    Or select the text and press <kbd>Ctrl+{example.shortcut}</kbd> (
                    <kbd>Cmd+{example.shortcut}</kbd> on a Mac).
                  </span>
                ) : null}
              </td>
              <td className="py-2">
                {/* Its heading is drawn, not a heading: the help is not part of the page's outline. */}
                <div className="text-sm leading-relaxed" data-rendered>
                  {renderMarkdown(example.syntax, { headingLevel: "none" })}
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
