import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReasonButton } from "./reason-button";

const REASON = "Approved: request changes or reset to rewrite";

describe("ReasonButton", () => {
  it("is a plain button while nothing holds it up", async () => {
    const onClick = vi.fn();
    render(
      <ReasonButton disabledReason={null} onClick={onClick}>
        Rewrite
      </ReasonButton>,
    );
    const button = screen.getByRole("button", { name: "Rewrite" });
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(button).not.toHaveAttribute("aria-describedby");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("says why it is unavailable, as visible text and as the button's description", () => {
    render(
      <ReasonButton disabledReason={REASON} onClick={() => undefined}>
        Rewrite
      </ReasonButton>,
    );
    const button = screen.getByRole("button", { name: "Rewrite", description: REASON });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    expect(button).toHaveClass("aria-disabled:opacity-50", "aria-disabled:pointer-events-none");
    expect(screen.getByText(REASON)).toBeVisible();
  });

  it("stays in the tab order, and ignores a click, Enter and Space", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <ReasonButton disabledReason={REASON} onClick={onClick}>
        Rewrite
      </ReasonButton>,
    );
    await user.tab();
    const button = screen.getByRole("button", { name: "Rewrite" });
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps focus when it becomes blocked, and works again once the reason is gone", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { rerender } = render(
      <ReasonButton disabledReason={null} onClick={onClick}>
        Rewrite
      </ReasonButton>,
    );
    await user.tab();
    rerender(
      <ReasonButton disabledReason={REASON} onClick={onClick}>
        Rewrite
      </ReasonButton>,
    );
    expect(screen.getByRole("button", { name: "Rewrite", description: REASON })).toHaveFocus();
    rerender(
      <ReasonButton disabledReason={null} onClick={onClick}>
        Rewrite
      </ReasonButton>,
    );
    expect(screen.queryByText(REASON)).toBeNull();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("passes keys other than Enter and Space to the caller, blocked or not", async () => {
    const user = userEvent.setup();
    const onKeyDown = vi.fn();
    render(
      <ReasonButton disabledReason={REASON} onKeyDown={onKeyDown}>
        Rewrite
      </ReasonButton>,
    );
    await user.tab();
    await user.keyboard("{Escape}");
    expect(onKeyDown).toHaveBeenCalledWith(expect.objectContaining({ key: "Escape" }));
  });

  it("does not submit its form while blocked", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((event: React.SubmitEvent<HTMLFormElement>) => event.preventDefault());
    render(
      <form aria-label="Brief" onSubmit={onSubmit}>
        <ReasonButton type="submit" disabledReason={REASON}>
          Save
        </ReasonButton>
      </form>,
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("adds its reason to a description the caller already gave", () => {
    render(
      <>
        <p id="hint">Only the owner can rewrite.</p>
        <ReasonButton disabledReason={REASON} aria-describedby="hint">
          Rewrite
        </ReasonButton>
      </>,
    );
    expect(screen.getByRole("button", { name: "Rewrite" })).toHaveAccessibleDescription(
      `Only the owner can rewrite. ${REASON}`,
    );
  });
});
