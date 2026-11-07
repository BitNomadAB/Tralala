import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Expander } from "./expander";

function details(): HTMLDetailsElement {
  const element = screen.getByText("Why it is needed").closest("details");
  if (!element) throw new Error("no <details>");
  return element;
}

describe("Expander", () => {
  it("is a <details> whose summary names it, with the hint after the title", () => {
    render(
      <Expander title="Pro and con" hint="3 for, 3 against">
        <p>Body</p>
      </Expander>,
    );
    const summary = screen.getByText("Pro and con");
    expect(summary.tagName).toBe("SUMMARY");
    expect(summary).toHaveTextContent("Pro and con3 for, 3 against");
    expect(screen.getByText("Body")).not.toBeVisible();
  });

  it("opens and closes on a click and tells onToggle each time", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <Expander title="Why it is needed" onToggle={onToggle}>
        <p>Because.</p>
      </Expander>,
    );
    expect(details().open).toBe(false);
    await user.click(screen.getByText("Why it is needed"));
    expect(details().open).toBe(true);
    await waitFor(() => expect(onToggle).toHaveBeenLastCalledWith(true));
    expect(screen.getByText("Because.")).toBeVisible();

    await user.click(screen.getByText("Why it is needed"));
    expect(details().open).toBe(false);
    await waitFor(() => expect(onToggle).toHaveBeenLastCalledWith(false));
  });

  it("follows `open` when it is controlled", async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [open, setOpen] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setOpen(false)}>
            Close it
          </button>
          <Expander title="Why it is needed" open={open} onToggle={setOpen}>
            <p>Because.</p>
          </Expander>
        </>
      );
    }
    render(<Controlled />);
    expect(details().open).toBe(true);
    await user.click(screen.getByRole("button", { name: "Close it" }));
    expect(details().open).toBe(false);
  });

  it("starts open with defaultOpen", () => {
    render(
      <Expander title="Why it is needed" defaultOpen>
        <p>Because.</p>
      </Expander>,
    );
    expect(details().open).toBe(true);
  });
});
