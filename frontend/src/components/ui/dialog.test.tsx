import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Dialog, DialogContent, DialogFrame, DialogTitle } from "./dialog";

/** A dialog opened from state, the way most dialogs here open: no DialogTrigger. */
function StateDialog({
  frame = false,
  removeOpenerOnClose = false,
  onCloseAutoFocus,
}: {
  frame?: boolean;
  removeOpenerOnClose?: boolean;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const [open, setOpen] = useState(false);
  const [openerShown, setOpenerShown] = useState(true);
  return (
    <>
      <button type="button">Before</button>
      {openerShown ? (
        <button type="button" onClick={() => setOpen(true)}>
          Open it
        </button>
      ) : null}
      <button type="button" id="elsewhere">
        Elsewhere
      </button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next && removeOpenerOnClose) setOpenerShown(false);
        }}
      >
        {frame ? (
          <DialogFrame>
            <DialogTitle>Framed</DialogTitle>
            <button type="button">Inside</button>
          </DialogFrame>
        ) : (
          <DialogContent title="Plain" onCloseAutoFocus={onCloseAutoFocus}>
            <button type="button">Inside</button>
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}

describe("dialog focus return", () => {
  it("gives focus back to the button that opened it from state", async () => {
    const user = userEvent.setup();
    render(<StateDialog />);
    await user.click(screen.getByRole("button", { name: "Open it" }));
    expect(screen.getByRole("dialog", { name: "Plain" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Open it" })).toHaveFocus();
  });

  it("does the same for a dialog that draws its own head", async () => {
    const user = userEvent.setup();
    render(<StateDialog frame />);
    await user.click(screen.getByRole("button", { name: "Open it" }));
    expect(screen.getByRole("dialog", { name: "Framed" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Open it" })).toHaveFocus();
  });

  it("leaves the last word to a caller that moves focus itself", async () => {
    const user = userEvent.setup();
    render(
      <StateDialog
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          document.getElementById("elsewhere")?.focus();
        }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Open it" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });

  it("does nothing when the opener has left the page", async () => {
    const user = userEvent.setup();
    render(<StateDialog removeOpenerOnClose />);
    await user.click(screen.getByRole("button", { name: "Open it" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "Open it" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
