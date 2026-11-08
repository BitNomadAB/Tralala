import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { CheckChip, Chip, StateChip, ToneMark } from "./chip";

describe("Chip", () => {
  it("shows its text with the trailing mark after it", () => {
    render(
      <Chip mono trailing={<span>done</span>}>
        PLN-014
      </Chip>,
    );
    const chip = screen.getByText("PLN-014");
    expect(chip).toHaveTextContent("PLN-014done");
    expect(chip).toHaveClass("font-mono");
  });

  it("is in the sans font unless mono", () => {
    render(<Chip>Label</Chip>);
    expect(screen.getByText("Label")).not.toHaveClass("font-mono");
  });
});

describe("StateChip", () => {
  it.each([
    ["ready", "Ready", "--success"],
    ["needs_input", "Needs input", "--warning"],
    ["blocked", "Blocked", "--destructive"],
  ] as const)("shows %s as %s with a dot in its colour", (state, word, colour) => {
    const { container } = render(<StateChip state={state} />);
    expect(screen.getByText(word)).toBeInTheDocument();
    const dot = container.querySelector('[aria-hidden="true"]');
    expect(dot?.className).toContain(`bg-[var(${colour})]`);
  });

  it("follows the word with the reason", () => {
    render(<StateChip state="blocked" reason="waits for PLN-017" />);
    expect(screen.getByText("Blocked").parentElement).toHaveTextContent(
      "Blocked· waits for PLN-017",
    );
  });

  it("is a small bordered pill when compact, with the longer reason for a pointer", () => {
    render(<StateChip state="needs_input" compact title="Which provider?" />);
    const chip = screen.getByText("Needs input").parentElement;
    expect(chip).toHaveClass("rounded-full", "border", "text-xs");
    expect(chip).toHaveAttribute("title", "Which provider?");
  });
});

describe("ToneMark", () => {
  it.each([
    ["success", "--success"],
    ["warning", "--warning"],
    ["danger", "--destructive"],
    ["neutral", "--foreground-faint"],
  ] as const)("marks a %s word with a dot the screen reader skips", (tone, colour) => {
    const { container } = render(<ToneMark tone={tone} word="Yes" />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
    const dot = container.querySelector('[aria-hidden="true"]');
    expect(dot?.className).toContain(`bg-[var(${colour})]`);
  });
});

function Choice({ initial }: { initial: boolean }) {
  const [checked, setChecked] = useState(initial);
  return <CheckChip checked={checked} onChange={setChecked} label="Alpha" detail="Product Owner" />;
}

describe("CheckChip", () => {
  it("is a checkbox named by its label and detail, and toggles", async () => {
    const user = userEvent.setup();
    render(<Choice initial />);
    const box = screen.getByRole("checkbox", { name: "Alpha Product Owner" });
    expect(box).toBeChecked();
    await user.click(screen.getByText("Alpha"));
    expect(box).not.toBeChecked();
  });

  it("does not toggle while disabled", async () => {
    const user = userEvent.setup();
    render(<CheckChip checked={false} onChange={() => undefined} label="Beta" disabled />);
    const box = screen.getByRole("checkbox", { name: "Beta" });
    await user.click(box);
    expect(box).toBeDisabled();
    expect(box).not.toBeChecked();
  });
});
