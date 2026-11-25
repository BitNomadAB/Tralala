import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Dialog, DialogContent } from "./dialog";
import { ToastProvider } from "./toast";
import { TOAST_DURATION_MS, useToast, type ToastInput } from "./useToast";

/** Four buttons that each push an error of its own. */
function NumberedFailures() {
  const toast = useToast();
  return [1, 2, 3, 4].map((number) => (
    <button
      key={number}
      type="button"
      onClick={() => {
        toast.push({ title: `Could not save ${String(number)}`, variant: "error" });
      }}
    >
      Fail {number}
    </button>
  ));
}

/** Buttons that push the toasts a test needs, and a dialog to push one from. */
function Pusher({ onUndo, numbered }: { onUndo: () => void; numbered: boolean }) {
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
      {numbered ? <NumberedFailures /> : null}
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

function renderToasts(numbered = false) {
  const onUndo = vi.fn<() => void>();
  const { container } = render(
    <ToastProvider>
      <Pusher onUndo={onUndo} numbered={numbered} />
    </ToastProvider>,
  );
  return { onUndo, container };
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

describe("where the toasts are drawn", () => {
  it("is the body, beside the app, so no dialog's backdrop covers a toast", () => {
    // The app's root is a stacking context under every dialog (index.css); inside it a toast
    // pushed while a dialog is open would be dimmed away. jsdom lays nothing out, so this holds
    // the place in the document that the stacking follows from.
    const { container } = renderToasts();
    press("Fail");
    expect(container).not.toContainElement(list("assertive"));
    expect(container).not.toContainElement(list("polite"));
    expect(list("assertive").parentElement?.parentElement).toBe(document.body);
    expect(list("assertive").parentElement).toHaveClass("fixed", "z-[60]");
  });
});

describe("a pile of toasts", () => {
  /** The titles of the toasts shown, errors first, oldest first. */
  const shown = () =>
    Array.from(document.querySelectorAll("[data-toast] p:first-child")).map(
      (title) => title.textContent,
    );

  it("shows at most three, the oldest leaving for a new one, so Dismiss stays in reach", () => {
    renderToasts(true);
    press("Fail 1");
    press("Fail 2");
    press("Fail 3");
    press("Fail 4");
    expect(shown()).toEqual(["Could not save 2", "Could not save 3", "Could not save 4"]);
  });

  it("lets a toast that leaves by itself make room before an error", () => {
    renderToasts(true);
    press("Save");
    press("Fail 1");
    press("Fail 2");
    press("Fail 3");
    expect(shown()).toEqual(["Could not save 1", "Could not save 2", "Could not save 3"]);
  });

  it("shows a toast again in place of the same one, instead of stacking it", () => {
    renderToasts();
    press("Fail");
    press("Save");
    press("Fail");
    expect(shown()).toEqual(["Could not save", "Saved"]);
    expect(screen.getAllByText("Busy")).toHaveLength(1);
  });

  it("keeps toasts with an action apart, as each Undo belongs to its own change", () => {
    renderToasts();
    press("Archive");
    press("Archive");
    expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(2);
  });
});
