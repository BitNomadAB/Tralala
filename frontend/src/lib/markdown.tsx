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
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      if (link && /^https?:\/\//i.test(link[2])) {
        nodes.push(
          <a
            key={`${keyPrefix}-a-${offset}`}
            href={link[2]}
            rel="noreferrer noopener"
            target="_blank"
          >
            {link[1]}
          </a>,
        );
      } else if (link) {
        nodes.push(link[1]);
      } else {
        nodes.push(token);
      }
    }
  }
  if (index < text.length) nodes.push(text.slice(index));
  return nodes;
}

export function renderMarkdown(source: string): ReactNode {
  if (!source.trim()) return null;
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push(
        <pre key={`code-${key++}`}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = renderInline(heading[2], `h-${key}`);
      const Tag = (["h1", "h2", "h3", "h4"] as const)[level - 1];
      blocks.push(<Tag key={`heading-${key++}`}>{content}</Tag>);
      index += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(
          <li key={`li-${key}-${items.length}`}>
            {renderInline(lines[index].replace(/^\s*[-*]\s+/, ""), `li-${key}-${items.length}`)}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ul key={`ul-${key++}`}>{items}</ul>);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(
          <li key={`oli-${key}-${items.length}`}>
            {renderInline(lines[index].replace(/^\s*\d+\.\s+/, ""), `oli-${key}-${items.length}`)}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ol key={`ol-${key++}`}>{items}</ol>);
      continue;
    }

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !/^\s*[-*]\s+/.test(lines[index]) &&
      !/^\s*\d+\.\s+/.test(lines[index]) &&
      !lines[index].trim().startsWith("```")
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={`p-${key++}`}>{renderInline(paragraph.join(" "), `p-${key}`)}</p>,
    );
  }

  return <>{blocks}</>;
}
