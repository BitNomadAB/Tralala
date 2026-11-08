import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { SelectMenu } from "./select-menu";

type Column = "backlog" | "progress" | "review" | "done";

const COLUMNS = [
  { value: "backlog", label: "Backlog", count: 13 },
  { value: "progress", label: "In Progress", count: 0 },
  { value: "review", label: "Review" },
  { value: "done", label: "Done", count: 21 },
] as const;

function Rail({ onChange }: { onChange: (value: Column) => void }) {
  const [column, setColumn] = useState<Column>("backlog");
  return (
    <>
      <p>Outside</p>
      <SelectMenu
        label="Column"
        value={column}
        options={COLUMNS}
        onChange={(next) => {
          setColumn(next);
          onChange(next);
        }}
      />
    </>
  );
}

function setup() {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<Rail onChange={onChange} />);
  return { user, onChange, button: screen.getByRole("button", { name: "Column: Backlog" }) };
}

describe("SelectMenu", () => {
  it("is a button naming the choice, collapsed until it is clicked", async () => {
    const { user, button } = setup();
    expect(button).toHaveAttribute("aria-haspopup", "listbox");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    await user.click(button);
    const list = screen.getByRole("listbox", { name: "Column" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAttribute("aria-controls", list.id);
    // The chosen option has the focus, as in a native select; counts are part of the name.
    const backlog = screen.getByRole("option", { name: "Backlog, 13" });
    expect(backlog).toHaveFocus();
    expect(backlog).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("option", { name: "Review" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("moves with the arrow keys, chooses on Enter and calls onChange once", async () => {
    const { user, onChange, button } = setup();
    await user.click(button);
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: "In Progress, 0" })).toHaveFocus();
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(screen.getByRole("option", { name: "Done, 21" })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("option", { name: "Review" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("review");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    const updated = screen.getByRole("button", { name: "Column: Review" });
    expect(updated).toHaveFocus();
    expect(updated).toHaveTextContent("Review");
  });

  it("goes to the first and last option on Home and End and chooses on Space", async () => {
    const { user, onChange, button } = setup();
    await user.click(button);
    await user.keyboard("{End}");
    expect(screen.getByRole("option", { name: "Done, 21" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("option", { name: "Backlog, 13" })).toHaveFocus();
    await user.keyboard("{End} ");
    expect(onChange.mock.calls).toEqual([["done"]]);
  });

  it("chooses an option that is clicked", async () => {
    const { user, onChange, button } = setup();
    await user.click(button);
    await user.click(screen.getByRole("option", { name: "Done, 21" }));
    expect(onChange.mock.calls).toEqual([["done"]]);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("closes on Escape without choosing and gives the focus back", async () => {
    const { user, onChange, button } = setup();
    await user.click(button);
    await user.keyboard("{ArrowDown}{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("closes on a click outside without choosing", async () => {
    const { user, onChange, button } = setup();
    await user.click(button);
    await user.click(screen.getByText("Outside"));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not call onChange for the option that is already chosen", async () => {
    const { user, onChange, button } = setup();
    await user.click(button);
    await user.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("opens from the keyboard with an arrow key and closes again on a second click", async () => {
    const { user, button } = setup();
    button.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: "Backlog, 13" })).toHaveFocus();
    await user.click(button);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("closes when Tab leaves the list", async () => {
    const { user, button } = setup();
    await user.click(button);
    await user.tab();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("can start open and reports every close, after the choice", async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    render(
      <SelectMenu
        label="Priority"
        value="none"
        options={[
          { value: "none", label: "None" },
          { value: "high", label: "High" },
        ]}
        defaultOpen
        onChange={(next) => calls.push(`change ${next}`)}
        onClose={() => calls.push("close")}
      />,
    );
    expect(screen.getByRole("option", { name: "None" })).toHaveFocus();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(calls).toEqual(["change high", "close"]);
    await user.click(screen.getByRole("button", { name: "Priority: None" }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Priority: None" }));
    await user.click(screen.getByRole("button", { name: "Priority: None" }));
    expect(calls).toEqual(["change high", "close", "close", "close"]);
  });
});
