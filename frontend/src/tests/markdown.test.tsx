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
});
