import type { ReactNode } from "react";

/**
 * Minimal, deliberately safe Markdown renderer.
 *
 * Card content is untrusted. The renderer never injects HTML: every text fragment becomes a
 * React text node, so `<script>` or inline handlers stay visible text instead of executing.
 * Only http(s) links are turned into anchors to other sites, and they open in a new tab; a Ticket
 * key becomes a link only when the page resolves it, and then only to a path on this site.
 */

export interface MarkdownOptions {
  /**
   * Turns a Ticket key (`AN001-RA02-001`) into the path of that Ticket, or null when the page
   * knows no such Ticket. The renderer has no board, so it finds keys by pattern and the page
   * decides; without a resolver every key stays text.
   */
  ticketHref?: ((key: string) => string | null) | undefined;
}

/**
 * A Ticket key exactly as the server issues it (`backend/app/services/loop_identifiers.py`): the
 * Loop key (two upper-case letters or digits and a sequence of at least three digits), then the
 * Phase prefix with a two-digit number or `UNP`, then a sequence of at least three digits.
 */
const TICKET_KEY =
  "(?<![A-Za-z0-9-])[A-Z0-9]{2}\\d{3,}-(?:[A-Z0-9]{2}\\d{2,}|UNP)-\\d{3,}(?![A-Za-z0-9-])";
const BARE_URL = "\\bhttps?:\\/\\/[^\\s<>]+";

const INLINE_PATTERN = new RegExp(
  [
    "\\*\\*[^*]+\\*\\*",
    "`[^`]+`",
    "\\*[^*]+\\*",
    "\\[[^\\]]+\\]\\([^)\\s]+\\)",
    BARE_URL,
    TICKET_KEY,
  ]
    .map((part) => `(?:${part})`)
    .join("|"),
  "g",
);
const BARE_URL_PATTERN = new RegExp(`^${BARE_URL}$`);
const TICKET_KEY_PATTERN = new RegExp(`^${TICKET_KEY}$`);
/** A path on this site; `//host` and `/\host` are other sites to a browser. */
const SAME_SITE_PATH = /^\/(?![/\\])/;

function count(text: string, character: string): number {
  return text.split(character).length - 1;
}

/** Leaves sentence punctuation after a bare URL out of it, and a `)` it did not open. */
function trimUrl(candidate: string): string {
  let url = candidate;
  for (let last = url.at(-1); last !== undefined; last = url.at(-1)) {
    const unopened = last === ")" && count(url, ")") > count(url, "(");
    if (!unopened && !".,;:!?'\"*_".includes(last)) break;
    url = url.slice(0, -1);
  }
  return url;
}

function externalLink(key: string, href: string, label: string): ReactNode {
  return (
    <a key={key} href={href} rel="noreferrer noopener" target="_blank">
      {label}
    </a>
  );
}

function renderToken(token: string, key: string, options: MarkdownOptions): ReactNode[] {
  if (token.startsWith("**") && token.endsWith("**") && token.length > 4) {
    return [<strong key={`${key}-b`}>{token.slice(2, -2)}</strong>];
  }
  if (token.startsWith("`") && token.endsWith("`") && token.length > 2) {
    return [<code key={`${key}-c`}>{token.slice(1, -1)}</code>];
  }
  if (token.startsWith("*") && token.endsWith("*") && token.length > 2) {
    return [<em key={`${key}-i`}>{token.slice(1, -1)}</em>];
  }
  const [, label, href] = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token) ?? [];
  if (label !== undefined && href !== undefined) {
    return [/^https?:\/\//i.test(href) ? externalLink(`${key}-a`, href, label) : label];
  }
  if (BARE_URL_PATTERN.test(token)) {
    const url = trimUrl(token);
    const rest = token.slice(url.length);
    if (!/^https?:\/\/[^/?#]/.test(url)) return [token];
    return rest ? [externalLink(`${key}-u`, url, url), rest] : [externalLink(`${key}-u`, url, url)];
  }
  if (TICKET_KEY_PATTERN.test(token)) {
    const path = options.ticketHref?.(token) ?? null;
    if (path !== null && SAME_SITE_PATH.test(path)) {
      return [
        <a key={`${key}-t`} href={path}>
          {token}
        </a>,
      ];
    }
  }
  return [token];
}

function renderInline(text: string, keyPrefix: string, options: MarkdownOptions): ReactNode[] {
  const nodes: ReactNode[] = [];
  let index = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const token = match[0];
    const offset = match.index;
    if (offset > index) nodes.push(text.slice(index, offset));
    index = offset + token.length;
    nodes.push(...renderToken(token, `${keyPrefix}-${offset}`, options));
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

export function renderMarkdown(source: string, options: MarkdownOptions = {}): ReactNode {
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
      const content = renderInline(text, `h-${key}`, options);
      const Tag = headingTag(hashes);
      blocks.push(<Tag key={`heading-${key++}`}>{content}</Tag>);
      index += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items = takeWhile((next) => /^\s*[-*]\s+/.test(next)).map((item, position) => (
        <li key={`li-${key}-${position}`}>
          {renderInline(item.replace(/^\s*[-*]\s+/, ""), `li-${key}-${position}`, options)}
        </li>
      ));
      blocks.push(<ul key={`ul-${key++}`}>{items}</ul>);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = takeWhile((next) => /^\s*\d+\.\s+/.test(next)).map((item, position) => (
        <li key={`oli-${key}-${position}`}>
          {renderInline(item.replace(/^\s*\d+\.\s+/, ""), `oli-${key}-${position}`, options)}
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
    blocks.push(<p key={`p-${key++}`}>{renderInline(paragraph.join(" "), `p-${key}`, options)}</p>);
  }

  return <>{blocks}</>;
}
