import type { ReactNode } from "react";

/**
 * Minimal, deliberately safe Markdown renderer.
 *
 * Card content is untrusted. The renderer never injects HTML: every text fragment becomes a
 * React text node, so `<script>` or inline handlers stay visible text instead of executing.
 * Only http(s) links are turned into anchors.
 */

const INLINE_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|\[[^\]]+\]\([^)\s]+\))/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let index = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const token = match[0];
    const offset = match.index;
    if (offset > index) nodes.push(text.slice(index, offset));
    index = offset + token.length;

    if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(<strong key={`${keyPrefix}-b-${offset}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(<code key={`${keyPrefix}-c-${offset}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("*") && token.endsWith("*")) {
      nodes.push(<em key={`${keyPrefix}-i-${offset}`}>{token.slice(1, -1)}</em>);
    } else {
      const [, label, href] = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token) ?? [];
      if (label !== undefined && href !== undefined && /^https?:\/\//i.test(href)) {
        nodes.push(
          <a key={`${keyPrefix}-a-${offset}`} href={href} rel="noreferrer noopener" target="_blank">
            {label}
          </a>,
        );
      } else if (label !== undefined) {
        nodes.push(label);
      } else {
        nodes.push(token);
      }
    }
  }
  if (index < text.length) nodes.push(text.slice(index));
  return nodes;
}

/** `#` to `####` become h1 to h4; the heading pattern admits nothing longer. */
function headingTag(hashes: string): "h1" | "h2" | "h3" | "h4" {
  switch (hashes.length) {
    case 1:
      return "h1";
    case 2:
      return "h2";
    case 3:
      return "h3";
    default:
      return "h4";
  }
}

export function renderMarkdown(source: string): ReactNode {
  if (!source.trim()) return null;
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;

  /** Consumes the lines from `index` on while `test` holds, and returns them. */
  const takeWhile = (test: (line: string) => boolean): string[] => {
    const taken: string[] = [];
    for (let line = lines[index]; line !== undefined && test(line); line = lines[index]) {
      taken.push(line);
      index += 1;
    }
    return taken;
  };

  for (let line = lines[index]; line !== undefined; line = lines[index]) {
    if (line.trim().startsWith("```")) {
      index += 1;
      const code = takeWhile((next) => !next.trim().startsWith("```"));
      index += 1;
      blocks.push(
        <pre key={`code-${key++}`}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const [, hashes, text] = /^(#{1,4})\s+(.*)$/.exec(line) ?? [];
    if (hashes !== undefined && text !== undefined) {
      const content = renderInline(text, `h-${key}`);
      const Tag = headingTag(hashes);
      blocks.push(<Tag key={`heading-${key++}`}>{content}</Tag>);
      index += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items = takeWhile((next) => /^\s*[-*]\s+/.test(next)).map((item, position) => (
        <li key={`li-${key}-${position}`}>
          {renderInline(item.replace(/^\s*[-*]\s+/, ""), `li-${key}-${position}`)}
        </li>
      ));
      blocks.push(<ul key={`ul-${key++}`}>{items}</ul>);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = takeWhile((next) => /^\s*\d+\.\s+/.test(next)).map((item, position) => (
        <li key={`oli-${key}-${position}`}>
          {renderInline(item.replace(/^\s*\d+\.\s+/, ""), `oli-${key}-${position}`)}
        </li>
      ));
      blocks.push(<ol key={`ol-${key++}`}>{items}</ol>);
      continue;
    }

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    // The line that got here always opens the paragraph, so the loop advances on any input. A
    // line such as "# a" + CR + "b" fails the heading pattern above but passes the heading test
    // below; when the paragraph started with that test, nothing was consumed and the page hung.
    index += 1;
    const paragraph = [
      line,
      ...takeWhile(
        (next) =>
          next.trim() !== "" &&
          !/^(#{1,4})\s+/.test(next) &&
          !/^\s*[-*]\s+/.test(next) &&
          !/^\s*\d+\.\s+/.test(next) &&
          !next.trim().startsWith("```"),
      ),
    ];
    blocks.push(<p key={`p-${key++}`}>{renderInline(paragraph.join(" "), `p-${key}`)}</p>);
  }

  return <>{blocks}</>;
}
