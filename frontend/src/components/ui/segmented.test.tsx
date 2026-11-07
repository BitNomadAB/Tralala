import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Segmented, SegmentedPanel } from "./segmented";

type View = "you" | "raw";

const OPTIONS = [
  { value: "you", label: "For you" },
  { value: "raw", label: "Raw text" },
] as const;

function WhatWillBeDone({ onChange }: { onChange?: (value: View) => void }) {
  const [view, setView] = useState<View>("you");
  return (
    <>
      <Segmented
        label="View"
        value={view}
        options={OPTIONS}
        idBase="what"
        onChange={(next) => {
          setView(next);
          onChange?.(next);
        }}
      />
      <SegmentedPanel idBase="what" value="you" active={view}>
        The steps
      </SegmentedPanel>
      <SegmentedPanel idBase="what" value="raw" active={view}>
        The agent&apos;s text
      </SegmentedPanel>
    </>
  );
}

describe("Segmented", () => {
  it("is a named tablist whose segments control their panels", () => {
    render(<WhatWillBeDone />);
    expect(screen.getByRole("tablist", { name: "View" })).toBeInTheDocument();
    const you = screen.getByRole("tab", { name: "For you" });
    const raw = screen.getByRole("tab", { name: "Raw text" });
    expect(you).toHaveAttribute("aria-selected", "true");
    expect(you).toHaveAttribute("tabindex", "0");
    expect(raw).toHaveAttribute("aria-selected", "false");
    expect(raw).toHaveAttribute("tabindex", "-1");
    expect(you).toHaveAttribute("aria-controls", "what-panel-you");
    expect(screen.getByRole("tabpanel", { name: "For you" })).toHaveTextContent("The steps");
    expect(screen.getByText("The agent's text")).not.toBeVisible();
  });

  it("moves the selection with the arrow keys, Home and End, and calls onChange with the value", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<WhatWillBeDone onChange={onChange} />);
    await user.click(screen.getByRole("tab", { name: "For you" }));
    expect(onChange).not.toHaveBeenCalled();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Raw text" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Raw text" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Raw text" })).toHaveTextContent("agent's text");

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "For you" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Raw text" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "For you" })).toHaveFocus();
    expect(onChange.mock.calls).toEqual([["raw"], ["you"], ["raw"], ["you"]]);
  });

  it("leaves aria-controls out without an idBase", () => {
    render(
      <Segmented
        label="Size"
        value="s"
        options={[{ value: "s", label: "S" }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("tab", { name: "S" })).not.toHaveAttribute("aria-controls");
  });
});
