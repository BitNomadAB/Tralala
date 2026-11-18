import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderDiscussion } from "./renderDiscussion";

function options(dialog: HTMLElement): HTMLDetailsElement {
  const details = dialog.querySelector("details");
  if (!(details instanceof HTMLDetailsElement)) throw new Error("No Options expander");
  return details;
}

describe("Let them talk it out: the options", () => {
  it("keeps Start pressable, opens the options and focuses the first field that is wrong", async () => {
    const { user, api } = await renderDiscussion();
    await user.click(screen.getByRole("button", { name: "Let them talk it out" }));
    const dialog = screen.getByRole("dialog", { name: "Let them talk it out" });
    const details = options(dialog);
    await user.click(within(dialog).getByText("Options"));
    const rounds = within(dialog).getByLabelText("Rounds");
    const tokens = within(dialog).getByLabelText("Token budget");
    await user.clear(rounds);
    await user.type(rounds, "9");
    await user.type(tokens, "a lot");
    // Closed again: Start opens it to show what is wrong.
    await user.click(within(dialog).getByText("Options"));
    expect(details.open).toBe(false);
    const start = within(dialog).getByRole("button", { name: "Start" });
    expect(start).not.toHaveAttribute("aria-disabled");
    await user.click(start);

    expect(details.open).toBe(true);
    await waitFor(() => expect(rounds).toHaveFocus());
    expect(rounds).toHaveAttribute("aria-invalid", "true");
    expect(rounds).toHaveAccessibleDescription(
      "Error: Use a whole number from 1 to 2. From 1 to 2.",
    );
    expect(tokens).toHaveAccessibleDescription(
      "Error: Use a whole number up to 5 000 000, or leave it empty. Empty means the server's default.",
    );
    expect(within(dialog).getByLabelText("Time budget in seconds")).not.toHaveAttribute(
      "aria-invalid",
    );
    expect(api.state.bodies).toEqual([]);

    // An error follows its field as it is corrected.
    await user.clear(rounds);
    await user.type(rounds, "2");
    expect(rounds).not.toHaveAttribute("aria-invalid");
    await user.clear(tokens);
    await user.click(start);
    await waitFor(() =>
      expect(api.state.bodies.map((write) => write.body)).toEqual([
        { autonomous: true, rounds: 2 },
      ]),
    );
  });
});

describe("the reply", () => {
  it("says to write something first when Ask again is pressed empty, and focuses the reply", async () => {
    const { user, api } = await renderDiscussion();
    const ask = screen.getByRole("button", { name: "Ask again" });
    expect(ask).not.toHaveAttribute("aria-disabled");
    await user.click(ask);
    const reply = screen.getByRole("textbox", { name: "Reply" });
    await waitFor(() => expect(reply).toHaveFocus());
    expect(reply).toHaveAttribute("aria-invalid", "true");
    expect(reply).toHaveAccessibleDescription(
      "Error: Write your reply first. The agents answer in a new round.",
    );
    expect(api.state.bodies).toEqual([]);
    await user.type(reply, "And if it is wrong?");
    expect(reply).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText("Write your reply first.")).toBeNull();
  });
});

describe("the decision", () => {
  it("holds Confirm on a veto with its reason until the explanation is written", async () => {
    const { user, api } = await renderDiscussion();
    await user.click(screen.getByRole("button", { name: "Veto" }));
    const review = screen.getByRole("dialog", { name: "Veto outcome" });
    const confirm = within(review).getByRole("button", {
      name: "Confirm",
      description: "Write the explanation first",
    });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    await user.click(confirm);
    expect(api.state.bodies).toEqual([]);
    await user.type(within(review).getByLabelText("Explanation"), "Not before the export owner.");
    expect(confirm).not.toHaveAttribute("aria-disabled");
    await user.click(confirm);
    await waitFor(() =>
      expect(api.state.bodies.map((write) => write.body)).toEqual([
        { decision: "veto", reason: "Not before the export owner." },
      ]),
    );
  });
});
