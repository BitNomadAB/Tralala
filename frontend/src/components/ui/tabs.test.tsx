import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Tab, TabList, TabPanel, Tabs } from "./tabs";

function Activity({ onChange }: { onChange?: (value: string) => void }) {
  const [value, setValue] = useState("comments");
  return (
    <Tabs
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    >
      <TabList label="Activity">
        <Tab value="comments">Comments</Tab>
        <Tab value="history">History</Tab>
        <Tab value="work">Work</Tab>
      </TabList>
      <TabPanel value="comments">No comments yet.</TabPanel>
      <TabPanel value="history">Nothing happened.</TabPanel>
      <TabPanel value="work">No work recorded yet.</TabPanel>
    </Tabs>
  );
}

function selectedName(): string | null {
  const selected = screen.getAllByRole("tab").find((tab) => tab.ariaSelected === "true");
  return selected?.textContent ?? null;
}

describe("Tabs", () => {
  it("is a named tablist whose selected tab is the one tab stop and controls the shown panel", () => {
    render(<Activity />);
    expect(screen.getByRole("tablist", { name: "Activity" })).toBeInTheDocument();
    const comments = screen.getByRole("tab", { name: "Comments" });
    const history = screen.getByRole("tab", { name: "History" });
    expect(comments).toHaveAttribute("aria-selected", "true");
    expect(comments).toHaveAttribute("tabindex", "0");
    expect(history).toHaveAttribute("aria-selected", "false");
    expect(history).toHaveAttribute("tabindex", "-1");

    const panel = screen.getByRole("tabpanel", { name: "Comments" });
    expect(comments).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveTextContent("No comments yet.");
    // The other panels are in the document but hidden, so only one is announced.
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByText("Nothing happened.").closest('[role="tabpanel"]')).toHaveAttribute(
      "hidden",
    );
  });

  it("moves focus and selection with the arrow keys, wrapping at the ends", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Activity onChange={onChange} />);
    await user.click(screen.getByRole("tab", { name: "Comments" }));
    expect(onChange).not.toHaveBeenCalled();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "History" })).toHaveFocus();
    expect(selectedName()).toBe("History");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Nothing happened.");

    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(selectedName()).toBe("Comments");

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Work" })).toHaveFocus();
    expect(selectedName()).toBe("Work");
    expect(onChange.mock.calls).toEqual([["history"], ["work"], ["comments"], ["work"]]);
  });

  it("goes to the first tab on Home and the last on End, and ignores other keys", async () => {
    const user = userEvent.setup();
    render(<Activity />);
    await user.click(screen.getByRole("tab", { name: "History" }));
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Work" })).toHaveFocus();
    expect(selectedName()).toBe("Work");
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "Comments" })).toHaveFocus();
    await user.keyboard("{ArrowDown}x");
    expect(selectedName()).toBe("Comments");
  });

  it("selects a tab that is clicked", async () => {
    const user = userEvent.setup();
    render(<Activity />);
    await user.click(screen.getByRole("tab", { name: "Work" }));
    expect(selectedName()).toBe("Work");
    expect(screen.getByRole("tabpanel", { name: "Work" })).toHaveTextContent("No work recorded");
  });

  it("refuses a Tab outside Tabs", () => {
    // React reports the thrown render error on the console; this test expects it.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Tab value="lost">Lost</Tab>)).toThrow("inside <Tabs>");
    quiet.mockRestore();
  });
});
