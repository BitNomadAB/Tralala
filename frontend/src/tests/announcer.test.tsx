import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ToastProvider } from "@/components/ui/toast";
import { ANNOUNCE_DELAY_MS, useAnnounce, useAnnounceWhen } from "@/components/ui/useAnnounce";
import { announcer } from "./announcer";

/** A view that says what happened when its buttons are pressed. */
function Saver() {
  const announce = useAnnounce();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => announce("Saved")}>
        Save
      </button>
      <button
        type="button"
        onClick={() => {
          announce("Ticket moved to Done");
          announce("2 Tickets left");
        }}
      >
        Move
      </button>
      <button type="button" onClick={() => announce("Connection lost", "assertive")}>
        Disconnect
      </button>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Edit column">
          <button type="button" onClick={() => announce("Column renamed")}>
            Rename
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}

function WritingNotice({ writing }: { writing: boolean }) {
  useAnnounceWhen(writing, "A board agent is writing the brief.");
  return null;
}

const press = (name: string) => {
  fireEvent.click(screen.getByRole("button", { name }));
};

const aTick = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ANNOUNCE_DELAY_MS);
  });

describe("announcing what happened", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("writes into live regions that are in the page before anything is said", async () => {
    render(
      <ToastProvider>
        <Saver />
      </ToastProvider>,
    );
    const polite = announcer("polite");
    expect(polite).toHaveAttribute("aria-live", "polite");
    expect(polite).toHaveAttribute("aria-atomic", "true");
    expect(polite).toHaveClass("sr-only");
    expect(polite).toBeEmptyDOMElement();
    expect(announcer("assertive")).toHaveAttribute("aria-live", "assertive");

    press("Save");
    expect(polite).toBeEmptyDOMElement();
    await aTick();
    expect(polite).toHaveTextContent("Saved");
  });

  it("clears the region before the same text, so it is read again", async () => {
    render(
      <ToastProvider>
        <Saver />
      </ToastProvider>,
    );
    press("Save");
    await aTick();
    expect(announcer()).toHaveTextContent("Saved");

    press("Save");
    expect(announcer()).toBeEmptyDOMElement();
    await aTick();
    expect(announcer()).toHaveTextContent("Saved");
  });

  it("reads what is sent in one go together, and the urgent apart from the rest", async () => {
    render(
      <ToastProvider>
        <Saver />
      </ToastProvider>,
    );
    press("Move");
    press("Disconnect");
    await aTick();
    expect(announcer("polite")).toHaveTextContent("Ticket moved to Done 2 Tickets left");
    expect(announcer("assertive")).toHaveTextContent("Connection lost");
  });

  it("stays readable while a dialog hides the rest of the page", async () => {
    render(
      <ToastProvider>
        <Saver />
      </ToastProvider>,
    );
    press("Open dialog");
    const dialog = screen.getByRole("dialog", { name: "Edit column" });
    // Radix hides the page behind the dialog from screen readers, but not the live regions.
    const page = screen.getByText("Save");
    expect(page.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(announcer().closest('[aria-hidden="true"]')).toBeNull();
    expect(dialog.contains(announcer())).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    await aTick();
    expect(announcer()).toHaveTextContent("Column renamed");
  });

  it("announces a status line each time it starts", async () => {
    const { rerender } = render(
      <ToastProvider>
        <WritingNotice writing={false} />
      </ToastProvider>,
    );
    await aTick();
    expect(announcer()).toBeEmptyDOMElement();

    rerender(
      <ToastProvider>
        <WritingNotice writing />
      </ToastProvider>,
    );
    await aTick();
    expect(announcer()).toHaveTextContent("A board agent is writing the brief.");
  });

  it("is only there under the provider", () => {
    // React reports the error it rethrows; the test only wants the throw.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Saver />)).toThrow("useAnnounce must be used within ToastProvider");
    consoleError.mockRestore();
  });
});
