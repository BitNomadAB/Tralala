import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HeldButton } from "./held-button";

describe("HeldButton", () => {
  it("stays focused and does nothing while held, and is disabled only when told so", async () => {
    const pressed: string[] = [];
    const { rerender } = render(
      <HeldButton held={false} onClick={() => pressed.push("save")}>
        Save
      </HeldButton>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save" }));
    rerender(
      <HeldButton held disabled onClick={() => pressed.push("save")}>
        Save
      </HeldButton>,
    );
    // Held wins over disabled, so the button that was pressed keeps the focus.
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toBeEnabled();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(pressed).toEqual(["save"]);

    rerender(
      <HeldButton held={false} disabled>
        Save
      </HeldButton>,
    );
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("is described by its reason only while held, beside its own description", () => {
    const { rerender } = render(
      <>
        <p id="own">Records the decision.</p>
        <p id="why">The run is still going.</p>
        <HeldButton held aria-describedby="own" reasonId="why">
          Approve
        </HeldButton>
      </>,
    );
    expect(
      screen.getByRole("button", {
        name: "Approve",
        description: "Records the decision. The run is still going.",
      }),
    ).toBeInTheDocument();
    rerender(
      <>
        <p id="own">Records the decision.</p>
        <p id="why">The run is still going.</p>
        <HeldButton held={false} aria-describedby="own" reasonId="why">
          Approve
        </HeldButton>
      </>,
    );
    const button = screen.getByRole("button", { name: "Approve" });
    expect(button).toHaveAttribute("aria-describedby", "own");
    expect(button).not.toHaveAttribute("aria-disabled");
  });

  it("does not submit its form while held", () => {
    const submitted: string[] = [];
    render(
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submitted.push("sent");
        }}
      >
        <HeldButton type="submit" held>
          Send
        </HeldButton>
      </form>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(submitted).toEqual([]);
  });
});
