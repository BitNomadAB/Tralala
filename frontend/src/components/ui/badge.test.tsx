import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { labelInk } from "@/lib/labelInk";
import { LabelChip } from "./badge";

describe("LabelChip", () => {
  it("writes the label in its readable ink for each mode and draws the border as chosen", () => {
    render(<LabelChip name="Backend" color="#64748b" />);
    const chip = screen.getByText("Backend");
    const ink = labelInk("#64748b");
    expect(chip).toHaveClass("label-ink");
    expect(chip.style.getPropertyValue("--label-ink-dark")).toBe(ink?.dark);
    expect(chip.style.getPropertyValue("--label-ink-light")).toBe(ink?.light);
    expect(chip.style.borderColor).toBe("rgb(100, 116, 139)");
  });

  it("leaves a colour that is not hex to the theme's text colour", () => {
    render(<LabelChip name="Odd" color="tomato" />);
    const chip = screen.getByText("Odd");
    expect(chip.style.getPropertyValue("--label-ink-dark")).toBe("");
    expect(chip.style.borderColor).toBe("tomato");
  });

  it("marks a chosen label with a check, not by colour or opacity", () => {
    const { rerender } = render(<LabelChip name="Backend" color="#64748b" />);
    expect(screen.getByText("Backend").querySelector("svg")).toBeNull();
    rerender(<LabelChip name="Backend" color="#64748b" selected />);
    const chip = screen.getByText("Backend");
    expect(chip.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(chip).toHaveTextContent(/^Backend$/);
    expect(chip.className).not.toMatch(/opacity/);
  });
});
