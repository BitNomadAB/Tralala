import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { MarkdownField } from "@/components/ui/markdown-field";
import { MarkdownHelp } from "@/components/ui/markdown-help";
import { FORMATTING_EXAMPLES, type FormattingExampleName } from "@/components/ui/markdownExamples";
import { CardDialogForm } from "@/features/cards/CardDialogForm";
import { ticketHrefResolver } from "@/features/loops/ticketLinks";

const LABEL = "Card description (Markdown)";

function Harness({
  initial = "",
  ticketHref,
}: {
  initial?: string;
  ticketHref?: (key: string) => string | null;
}) {
  const [value, setValue] = useState(initial);
  const [preview, setPreview] = useState(false);
  return (
    <MarkdownField
      id="description"
      title="Description"
      label={LABEL}
      value={value}
      onChange={setValue}
      preview={preview}
      onPreviewChange={setPreview}
      ticketHref={ticketHref}
    />
  );
}

function field(): HTMLTextAreaElement {
  const element = screen.getByLabelText(LABEL);
  if (!(element instanceof HTMLTextAreaElement)) throw new Error("not a textarea");
  return element;
}

function select(start: number, end: number) {
  field().focus();
  field().setSelectionRange(start, end);
}

describe("MarkdownField tabs", () => {
  it("switches between Write and Preview by click and by keyboard", async () => {
    const user = userEvent.setup();
    render(<Harness initial="Some **bold** text" />);
    const tablist = screen.getByRole("tablist", { name: "Description" });
    const write = within(tablist).getByRole("tab", { name: "Write" });
    const preview = within(tablist).getByRole("tab", { name: "Preview" });
    expect(write).toHaveAttribute("aria-selected", "true");
    expect(field()).toBeVisible();

    await user.click(preview);
    expect(preview).toHaveAttribute("aria-selected", "true");
    expect(field()).not.toBeVisible();
    const panel = screen.getByRole("tabpanel", { name: "Preview" });
    expect(within(panel).getByText("bold").tagName).toBe("STRONG");

    await user.keyboard("{ArrowLeft}");
    expect(write).toHaveAttribute("aria-selected", "true");
    expect(write).toHaveFocus();
    await user.keyboard("{End}");
    expect(preview).toHaveFocus();
    expect(preview).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}");
    expect(write).toHaveAttribute("aria-selected", "true");
    expect(write).toHaveAttribute("tabindex", "0");
    expect(preview).toHaveAttribute("tabindex", "-1");
  });

  it("says when there is nothing to preview", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByText("Nothing to preview yet")).toBeVisible();
  });

  it("links a Ticket key the page resolves in the preview", async () => {
    const user = userEvent.setup();
    const ticketHref = ticketHrefResolver("b-1", "l-1", [
      { id: "c-9", ticket_key: "AN001-RA02-001" },
      { id: "c-8", ticket_key: null },
    ]);
    render(<Harness initial="After AN001-RA02-001 and AN001-RA02-002" ticketHref={ticketHref} />);
    await user.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByRole("link", { name: "AN001-RA02-001" })).toHaveAttribute(
      "href",
      "/boards/b-1/loops/l-1?card=c-9",
    );
    expect(screen.queryByRole("link", { name: "AN001-RA02-002" })).toBeNull();
  });
});

describe("MarkdownField shortcuts", () => {
  it("wraps the selection in ** on Ctrl+B and in * on Cmd+I", async () => {
    const user = userEvent.setup();
    render(<Harness initial="make this loud" />);
    select(10, 14);
    await user.keyboard("{Control>}b{/Control}");
    expect(field().value).toBe("make this **loud**");
    expect([field().selectionStart, field().selectionEnd]).toEqual([12, 16]);

    select(5, 9);
    await user.keyboard("{Meta>}i{/Meta}");
    expect(field().value).toBe("make *this* **loud**");
  });

  it("only inserts the markers on an empty selection", async () => {
    const user = userEvent.setup();
    render(<Harness initial="ab" />);
    select(1, 1);
    await user.keyboard("{Control>}b{/Control}");
    expect(field().value).toBe("a****b");
    expect([field().selectionStart, field().selectionEnd]).toEqual([3, 3]);
    await user.keyboard("{Control>}k{/Control}");
    expect(field().value).toBe("a**[](url)**b");
    expect([field().selectionStart, field().selectionEnd]).toEqual([4, 4]);
  });

  it("makes a link on Ctrl+K and takes the typed address over the placeholder", async () => {
    const user = userEvent.setup();
    render(<Harness initial="read the guide" />);
    select(9, 14);
    await user.keyboard("{Control>}k{/Control}");
    expect(field().value).toBe("read the [guide](url)");
    expect(field().value.slice(field().selectionStart, field().selectionEnd)).toBe("url");
    await user.keyboard("https://example.com");
    expect(field().value).toBe("read the [guide](https://example.com)");
  });

  it("keeps the pasted address in the brackets Ctrl+K left", async () => {
    const user = userEvent.setup();
    render(<Harness initial="guide" />);
    select(0, 5);
    await user.keyboard("{Control>}k{/Control}");
    await user.paste("https://example.com");
    expect(field().value).toBe("[guide](https://example.com)");
  });

  it("makes a link when an address is pasted over a selection, and pastes plainly otherwise", async () => {
    const user = userEvent.setup();
    render(<Harness initial="see the docs" />);
    select(8, 12);
    await user.paste("  https://example.com/docs ");
    expect(field().value).toBe("see the [docs](https://example.com/docs)");
    expect(field().selectionStart).toBe(field().value.length);

    select(0, 3);
    await user.paste("read");
    expect(field().value).toBe("read the [docs](https://example.com/docs)");

    select(0, 4);
    await user.paste("javascript:alert(1)");
    expect(field().value).toBe("javascript:alert(1) the [docs](https://example.com/docs)");
  });

  it("leaves other keys and Ctrl+Shift combinations alone", () => {
    render(<Harness initial="text" />);
    select(0, 4);
    fireEvent.keyDown(field(), { key: "b", ctrlKey: true, shiftKey: true });
    fireEvent.keyDown(field(), { key: "u", ctrlKey: true });
    fireEvent.keyDown(field(), { key: "b" });
    expect(field().value).toBe("text");
  });
});

/** What every example in "How to format" must render to; a new example fails until it has one. */
const RENDERS_TO: Record<FormattingExampleName, (cell: HTMLElement) => void> = {
  bold: (cell) => expect(cell.querySelector("strong")).toHaveTextContent("important"),
  italic: (cell) => expect(cell.querySelector("em")).toHaveTextContent("a little emphasis"),
  inlineCode: (cell) => expect(cell.querySelector("p code")).toHaveTextContent("settings.json"),
  heading: (cell) => expect(cell.querySelector("h2")).toHaveTextContent("Next steps"),
  bulletList: (cell) => expect(cell.querySelectorAll("ul li")).toHaveLength(2),
  numberedList: (cell) => expect(cell.querySelectorAll("ol li")).toHaveLength(2),
  link: (cell) => {
    const anchor = cell.querySelector("a");
    expect(anchor).toHaveTextContent("Example");
    expect(anchor).toHaveAttribute("href", "https://example.com");
    expect(anchor).toHaveAttribute("target", "_blank");
  },
  webAddress: (cell) =>
    expect(cell.querySelector("a")).toHaveAttribute("href", "https://example.com"),
  codeBlock: (cell) => expect(cell.querySelector("pre code")).toHaveTextContent("line one"),
  paragraphBreak: (cell) => expect(cell.querySelectorAll("p")).toHaveLength(2),
};

describe("How to format", () => {
  it("is closed by default and renders every example to its element", () => {
    const { container } = render(<MarkdownHelp />);
    const details = container.querySelector("details");
    expect(details).not.toHaveAttribute("open");
    expect(within(container).getByText("How to format").tagName).toBe("SUMMARY");
    expect(
      within(container).getByText(
        "Links to other sites open in a new tab; only http(s) links become links.",
      ),
    ).toBeInTheDocument();

    expect(Object.keys(FORMATTING_EXAMPLES).sort()).toEqual(Object.keys(RENDERS_TO).sort());
    expect(container.querySelectorAll("tbody tr")).toHaveLength(Object.keys(RENDERS_TO).length);
    for (const [name, check] of Object.entries(RENDERS_TO)) {
      const row = container.querySelector(`tr[data-example="${name}"]`);
      const cell = row?.querySelector<HTMLElement>("[data-rendered]");
      if (!cell) throw new Error(`no rendered cell for ${name}`);
      check(cell);
    }
  });
});

describe("CardDialogForm description", () => {
  it("edits the description through the Markdown field and saves it once it changed", async () => {
    const user = userEvent.setup();
    const saved: string[] = [];
    function Form() {
      const [description, setDescription] = useState("");
      const [preview, setPreview] = useState(false);
      return (
        <CardDialogForm
          description={description}
          onDescriptionChange={setDescription}
          preview={preview}
          onPreviewChange={setPreview}
          dirty={description !== ""}
          saving={false}
          onSave={() => saved.push(description)}
        />
      );
    }
    render(<Form />);
    const save = screen.getByRole("button", { name: "Save description" });
    expect(save).toBeDisabled();
    await user.type(field(), "hi");
    await user.click(save);
    expect(saved).toEqual(["hi"]);
    // The title and priority moved to the Ticket's head and rail (ticket-view.test.tsx).
    expect(screen.queryByLabelText("Title")).toBeNull();
    expect(screen.queryByLabelText("Priority")).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByRole("tabpanel", { name: "Preview" })).toHaveTextContent("hi");
  });

  it("offers no Save on a read-only Ticket", () => {
    render(
      <CardDialogForm
        description="Saved"
        onDescriptionChange={() => undefined}
        preview={false}
        onPreviewChange={() => undefined}
        dirty={false}
        saving={false}
        onSave={() => undefined}
        readOnly
      />,
    );
    expect(screen.queryByRole("button", { name: "Save description" })).toBeNull();
  });
});
