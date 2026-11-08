import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Menu } from "./menu";

function setup() {
  const user = userEvent.setup();
  const edit = vi.fn();
  const archive = vi.fn();
  const remove = vi.fn();
  render(
    <>
      <p>Outside</p>
      <Menu
        label="Board actions"
        items={[
          { label: "Edit board", onSelect: edit },
          { label: "Delete board", onSelect: remove, disabled: true, hint: "Archive it first" },
          { label: "Archive board", onSelect: archive, danger: true },
        ]}
      />
    </>,
  );
  const button = screen.getByRole("button", { name: "Board actions" });
  return { user, edit, archive, remove, button };
}

describe("Menu", () => {
  it("is a quiet button that opens a menu with the first item focused", async () => {
    const { user, button } = setup();
    expect(button).toHaveAttribute("aria-haspopup", "menu");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu", { name: "Board actions" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Edit board" })).toHaveFocus();
  });

  it("moves with the arrow keys past a disabled item and runs the chosen one with Enter", async () => {
    const { user, button, archive } = setup();
    button.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Edit board" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Archive board" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("menuitem", { name: "Edit board" })).toHaveFocus();
    await user.keyboard("{End}{Enter}");
    expect(archive).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
  });

  it("shows a disabled item with its reason and does not run it", async () => {
    const { user, button, remove } = setup();
    await user.click(button);
    const item = screen.getByRole("menuitem", { name: /Delete board/ });
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(item).toHaveAccessibleName("Delete board: Archive it first");
    await user.click(item);
    expect(remove).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("runs an item on click, and closes on Escape or a click outside without running any", async () => {
    const { user, button, edit, archive } = setup();
    await user.click(button);
    await user.click(screen.getByRole("menuitem", { name: "Edit board" }));
    expect(edit).toHaveBeenCalledOnce();

    await user.click(button);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();

    await user.click(button);
    await user.click(screen.getByText("Outside"));
    expect(screen.queryByRole("menu")).toBeNull();

    await user.click(button);
    await user.keyboard("{Tab}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(archive).not.toHaveBeenCalled();
  });
});
