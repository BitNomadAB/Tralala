import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { TemplateListsField } from "@/features/settings/TemplateListsField";
import { announcer } from "./announcer";

function Field({ initial }: { initial: string[] }) {
  const [lists, setLists] = useState(initial);
  return <TemplateListsField lists={lists} onListsChange={setLists} />;
}

function renderField(initial: string[]) {
  render(
    <ToastProvider>
      <Field initial={initial} />
    </ToastProvider>,
  );
  return userEvent.setup();
}

/** The fields' values, top to bottom. */
const values = () =>
  screen
    .getAllByRole("textbox")
    .map((field) => (field instanceof HTMLInputElement ? field.value : null));

describe("the template's lists", () => {
  it("name their buttons after the list, or its number while it has none", () => {
    renderField(["Backlog", ""]);
    expect(screen.getByRole("button", { name: "Move Backlog down" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Move Backlog up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Backlog" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move list 2 up" })).toBeEnabled();
  });

  it("move a list, keep the focus on its button and say its new position", async () => {
    const user = renderField(["Backlog", "Doing", "Done"]);
    await user.click(screen.getByRole("button", { name: "Move Backlog down" }));
    expect(values()).toEqual(["Doing", "Backlog", "Done"]);
    expect(screen.getByRole("button", { name: "Move Backlog down" })).toHaveFocus();
    await waitFor(() => {
      expect(announcer()).toHaveTextContent("Backlog moved to position 2 of 3.");
    });

    // At the end the button it pressed is disabled; the focus stays in the row, on the other one.
    await user.keyboard("{Enter}");
    expect(values()).toEqual(["Doing", "Done", "Backlog"]);
    expect(screen.getByRole("button", { name: "Move Backlog down" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move Backlog up" })).toHaveFocus();
  });

  it("keep each field with its list while lists move and go", async () => {
    const user = renderField(["Ideas", "Doing"]);
    const ideas = screen.getByRole("textbox", { name: "List 1" });
    await user.click(screen.getByRole("button", { name: "Move Ideas down" }));
    expect(screen.getByRole("textbox", { name: "List 2" })).toBe(ideas);
    await user.click(screen.getByRole("button", { name: "Remove Doing" }));
    expect(values()).toEqual(["Ideas"]);
    await user.click(screen.getByRole("button", { name: "Remove Ideas" }));
    expect(values()).toEqual([""]);
    await user.click(screen.getByRole("button", { name: "Add list" }));
    expect(values()).toEqual(["", ""]);
  });
});
