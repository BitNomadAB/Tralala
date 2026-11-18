import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Dialog, DialogContent } from "./dialog";
import { ToastProvider } from "./toast";
import { TOAST_DURATION_MS, useToast, type ToastInput } from "./useToast";

/** Buttons that push the toasts a test needs, and a dialog to push one from. */
function Pusher({ onUndo }: { onUndo: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const push = (input: ToastInput) => () => {
    toast.push(input);
  };
  return (
    <>
      <button
        type="button"
        onClick={push({ title: "Could not save", description: "Busy", variant: "error" })}
      >
        Fail
      </button>
      <button type="button" onClick={push({ title: "Saved", variant: "success" })}>
        Save
      </button>
      <button
        type="button"
        onClick={push({ title: "Ticket archived", action: { label: "Undo", onClick: onUndo } })}
      >
        Archive
      </button>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Edit Ticket">
          <button type="button" onClick={push({ title: "Could not save", variant: "error" })}>
            Save Ticket
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}

function renderToasts() {
  const onUndo = vi.fn<() => void>();
  render(
    <ToastProvider>
      <Pusher onUndo={onUndo} />
    </ToastProvider>,
  );
  return { onUndo };
}

function list(live: "polite" | "assertive"): HTMLElement {
  const element = document.querySelector<HTMLElement>(`[data-toasts="${live}"]`);
  if (!element) throw new Error(`no ${live} toast list`);
  return element;
}

const press = (name: string) => {
  fireEvent.click(screen.getByRole("button", { name }));
};

function later(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

/** The toast a text is in: what the pointer rests on and focus sits in. */
function toastOf(text: string): HTMLElement {
  const toast = screen.getByText(text).closest<HTMLElement>("[data-toast]");
  if (!toast) throw new Error(`"${text}" is not in a toast`);
  return toast;
}

// Fake time and fireEvent: user-event waits on a real timer between its steps.
describe("a toast's time", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not run out for an error, which is read at once from a list that was there first", () => {
    renderToasts();
    expect(list("assertive")).toHaveAttribute("aria-live", "assertive");
    expect(list("assertive")).toBeEmptyDOMElement();
    expect(list("polite")).toHaveAttribute("aria-live", "polite");
    expect(list("polite")).toBeEmptyDOMElement();

    press("Fail");
    expect(list("assertive")).toHaveTextContent("Could not save");
    expect(list("assertive")).toHaveTextContent("Busy");
    expect(list("polite")).toBeEmptyDOMElement();

    later(10 * 60_000);
    expect(screen.getByText("Could not save")).toBeInTheDocument();
    press("Dismiss notification");
    expect(screen.queryByText("Could not save")).not.toBeInTheDocument();
  });

  it("runs out for any other toast, which is read politely", () => {
    renderToasts();
    press("Save");
    expect(list("polite")).toHaveTextContent("Saved");

    later(TOAST_DURATION_MS - 1);
    expect(screen.getByText("Saved")).toBeInTheDocument();
    later(1);
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("does not run out for a toast with an action, which may be the only way back", () => {
    renderToasts();
    press("Archive");
    expect(list("polite")).toHaveTextContent("Ticket archived");

    later(10 * 60_000);
    expect(screen.getByText("Ticket archived")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("stands still while the pointer is on the toast, then the rest of it runs", () => {
    renderToasts();
    press("Save");
    later(2000);
    fireEvent.pointerEnter(toastOf("Saved"));
    later(60_000);
    expect(screen.getByText("Saved")).toBeInTheDocument();

    fireEvent.pointerLeave(toastOf("Saved"));
    later(TOAST_DURATION_MS - 2000 - 1);
    expect(screen.getByText("Saved")).toBeInTheDocument();
    later(1);
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("stands still while focus is in the toast", () => {
    renderToasts();
    press("Save");
    const dismiss = screen.getByRole("button", { name: "Dismiss notification" });
    act(() => {
      dismiss.focus();
    });
    later(60_000);
    expect(screen.getByText("Saved")).toBeInTheDocument();

    act(() => {
      screen.getByRole("button", { name: "Fail" }).focus();
    });
    later(TOAST_DURATION_MS - 1);
    expect(screen.getByText("Saved")).toBeInTheDocument();
    later(1);
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });
});

describe("a toast's buttons", () => {
  it("are reached and pressed from the keyboard, after the page", async () => {
    renderToasts();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Fail" }));
    await user.tab();
    await user.tab();
    await user.tab();
    await user.tab();
    expect(screen.getByRole("button", { name: "Dismiss notification" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.queryByText("Could not save")).not.toBeInTheDocument();
  });

  it("run the toast's action and close it", async () => {
    const { onUndo } = renderToasts();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Ticket archived")).not.toBeInTheDocument();
  });

  it("dismiss a toast over an open dialog without closing the dialog", async () => {
    renderToasts();
    // The modal dialog turns pointer events off outside it; the toast turns them on again with
    // CSS that jsdom does not load, so this press skips user-event's check.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await user.click(screen.getByRole("button", { name: "Open dialog" }));
    await user.click(screen.getByRole("button", { name: "Save Ticket" }));
    expect(list("assertive")).toHaveTextContent("Could not save");

    await user.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Could not save")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Edit Ticket" })).toBeInTheDocument();
  });
});
