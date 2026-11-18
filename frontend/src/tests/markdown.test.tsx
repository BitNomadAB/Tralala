import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderMarkdown } from "@/lib/markdown";

describe("renderMarkdown", () => {
  it("renders headings, emphasis and inline code", () => {
    render(
      <div data-testid="root">{renderMarkdown("# Title\n\nSome **bold** and `code` text.")}</div>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Title");
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
  });

  it("never executes embedded HTML", () => {
    const { container } = render(
      <div>
        {renderMarkdown(
          '<script>window.__pwned = true</script> and <img src=x onerror="alert(1)">',
        )}
      </div>,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>");
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("only links http(s) URLs", () => {
    const { container } = render(
      <div>{renderMarkdown("[ok](https://example.com) [bad](javascript:alert(1))")}</div>,
    );
    const anchors = container.querySelectorAll("a");
    expect(anchors).toHaveLength(1);
    expect(anchors[0]?.getAttribute("href")).toBe("https://example.com");
    expect(anchors[0]?.getAttribute("rel")).toContain("noreferrer");
    expect(container.textContent).toContain("bad");
  });

  it("renders lists and code blocks", () => {
    const { container } = render(
      <div>{renderMarkdown("- one\n- two\n\n```\nconst a = 1;\n```")}</div>,
    );
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("pre code")?.textContent).toContain("const a = 1;");
  });

  it("renders four heading levels, ordered lists and joined paragraph lines", () => {
    const { container } = render(
      <div>
        {renderMarkdown("# a\n## b\n### c\n#### d\n##### e\n\n1. one\n2. two\nfirst\nsecond")}
      </div>,
    );
    expect([...container.querySelectorAll("h1, h2, h3, h4")].map((node) => node.tagName)).toEqual([
      "H1",
      "H2",
      "H3",
      "H4",
    ]);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect([...container.querySelectorAll("p")].map((node) => node.textContent)).toEqual([
      "##### e",
      "first second",
    ]);
  });

  it("renders a heading marker the heading pattern rejects as a paragraph, without hanging", () => {
    for (const separator of ["\r", "\u2028"]) {
      const { container, unmount } = render(<div>{renderMarkdown(`# a${separator}b\nnext`)}</div>);
      expect(container.querySelector("h1")).toBeNull();
      expect([...container.querySelectorAll("p")].map((node) => node.textContent)).toEqual([
        `# a${separator}b next`,
      ]);
      unmount();
    }
  });

  it("keeps javascript: and mailto: addresses as text, written or bare", () => {
    const { container } = render(
      <div>
        {renderMarkdown(
          "[run](javascript:run) [mail](mailto:a@example.com) javascript:alert(2) mailto:b@example.com",
        )}
      </div>,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toBe("run mail javascript:alert(2) mailto:b@example.com");
  });
});

describe("renderMarkdown bare URLs", () => {
  it("links a bare address in a new tab and leaves trailing punctuation out", () => {
    const { container } = render(
      <div>
        {renderMarkdown(
          "See https://example.com/a?b=1. Or (http://example.org/x), and https://en.example.com/T_(1)!",
        )}
      </div>,
    );
    const anchors = [...container.querySelectorAll("a")];
    expect(anchors.map((anchor) => anchor.getAttribute("href"))).toEqual([
      "https://example.com/a?b=1",
      "http://example.org/x",
      "https://en.example.com/T_(1)",
    ]);
    expect(anchors.every((anchor) => anchor.getAttribute("target") === "_blank")).toBe(true);
    expect(anchors.every((anchor) => anchor.getAttribute("rel") === "noreferrer noopener")).toBe(
      true,
    );
    // Each link says, to a screen reader, that it opens a new tab.
    expect(container.textContent).toBe(
      "See https://example.com/a?b=1 (opens in a new tab). Or (http://example.org/x (opens in a new tab)), and https://en.example.com/T_(1) (opens in a new tab)!",
    );
  });

  it("keeps an address in a code span or a code block as text", () => {
    const { container } = render(
      <div>
        {renderMarkdown("Run `curl https://example.com` now\n\n```\nhttps://example.org\n```")}
      </div>,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("p code")?.textContent).toBe("curl https://example.com");
    expect(container.querySelector("pre code")?.textContent).toBe("https://example.org");
  });

  it("does not link an address with no host or one glued to a word", () => {
    const { container } = render(<div>{renderMarkdown("https://. and xhttps://example.com")}</div>);
    expect(container.querySelector("a")).toBeNull();
  });
});

describe("renderMarkdown Ticket keys", () => {
  const known: Record<string, string> = {
    "AN001-RA02-001": "/boards/b-1/loops/l-1?card=c-1",
    "AN001-UNP-012": "/boards/b-1/loops/l-1?card=c-2",
    "AN001-QA01-1000": "/boards/b-1/loops/l-1?card=c-3",
  };
  const ticketHref = (key: string) => known[key] ?? null;

  it("links a key the page knows to that Ticket, in the same tab", () => {
    const { container } = render(
      <div>
        {renderMarkdown("Needs AN001-RA02-001, AN001-UNP-012 and AN001-QA01-1000.", {
          ticketHref,
        })}
      </div>,
    );
    const anchors = [...container.querySelectorAll("a")];
    expect(anchors.map((anchor) => [anchor.textContent, anchor.getAttribute("href")])).toEqual([
      ["AN001-RA02-001", "/boards/b-1/loops/l-1?card=c-1"],
      ["AN001-UNP-012", "/boards/b-1/loops/l-1?card=c-2"],
      ["AN001-QA01-1000", "/boards/b-1/loops/l-1?card=c-3"],
    ]);
    expect(anchors.every((anchor) => !anchor.hasAttribute("target"))).toBe(true);
  });

  it("keeps unknown keys, near-keys and keys without a resolver as text", () => {
    const asked: string[] = [];
    const { container, unmount } = render(
      <div>
        {renderMarkdown(
          "BE09-RA02-001 an001-ra02-001 AN01-RA02-001 AN001-RA2-001 AN001-RA02-01 XAN001-RA02-001 AN001-RA02-001-2 AN001-BE01-003 `AN001-RA02-001`",
          {
            ticketHref: (key) => {
              asked.push(key);
              return ticketHref(key);
            },
          },
        )}
      </div>,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(asked).toEqual(["AN001-BE01-003"]);
    unmount();

    const { container: plain } = render(<div>{renderMarkdown("Needs AN001-RA02-001.")}</div>);
    expect(plain.querySelector("a")).toBeNull();
  });

  it("refuses a resolver's answer that leaves the site", () => {
    for (const href of [
      "https://example.com",
      "//example.com/x",
      "/\\example.com",
      "javascript:x",
    ]) {
      const { container, unmount } = render(
        <div>{renderMarkdown("AN001-RA02-001", { ticketHref: () => href })}</div>,
      );
      expect(container.querySelector("a")).toBeNull();
      expect(container.textContent).toBe("AN001-RA02-001");
      unmount();
    }
  });
});

describe("renderMarkdown for a page", () => {
  it("puts the whole text in one prose container, and nothing for empty text", () => {
    const { container } = render(<div>{renderMarkdown("One.\n\n- two\n\n# three")}</div>);
    const root = container.firstElementChild;
    expect(root?.children).toHaveLength(1);
    const prose = root?.firstElementChild;
    expect(prose).toHaveClass("prose-card");
    expect([...(prose?.children ?? [])].map((node) => node.tagName)).toEqual(["P", "UL", "H1"]);
    expect(renderMarkdown("  \n ")).toBeNull();
  });

  it("starts the headings at the level it is given and stops at h6", () => {
    const { container } = render(
      <div>{renderMarkdown("# a\n## b\n### c\n#### d", { headingLevel: 4 })}</div>,
    );
    const headings = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")];
    expect(headings.map((node) => node.tagName)).toEqual(["H4", "H5", "H6", "H6"]);
    // The size follows the hashes, so the text keeps its own order of sizes.
    expect(headings.map((node) => node.className)).toEqual([
      "md-heading md-h1",
      "md-heading md-h2",
      "md-heading md-h3",
      "md-heading md-h4",
    ]);
  });

  it("draws headings without putting them in the outline under none", () => {
    render(<div>{renderMarkdown("## Next steps", { headingLevel: "none" })}</div>);
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.getByText("Next steps")).toHaveClass("md-heading", "md-h2");
  });

  it("says that a link to another site opens a new tab, with an icon hidden from readers", () => {
    render(
      <div>
        {renderMarkdown("[Example](https://example.com) and AN001-RA02-001", {
          ticketHref: () => "/boards/b-1/loops/l-1?card=c-1",
        })}
      </div>,
    );
    const external = screen.getByRole("link", { name: "Example (opens in a new tab)" });
    expect(external).toHaveAttribute("target", "_blank");
    expect(external.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    // A Ticket on this site opens in the same tab and says nothing more.
    expect(screen.getByRole("link", { name: "AN001-RA02-001" })).not.toHaveAttribute("target");
  });

  it("lets a keyboard reach a code block, which is a named group", () => {
    render(<div>{renderMarkdown("```\na very long line\n```")}</div>);
    const block = screen.getByRole("group", { name: "Code block" });
    expect(block.tagName).toBe("PRE");
    expect(block).toHaveAttribute("tabindex", "0");
  });
});
