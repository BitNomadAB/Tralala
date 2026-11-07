import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Avatar } from "./avatar";

describe("Avatar", () => {
  it.each([
    ["Mike Hansen", "MH"],
    ["Mike", "M"],
    ["  ada   byron lovelace ", "AB"],
    ["", "?"],
  ])("derives the initials of %j as %s", (name, initials) => {
    render(<Avatar name={name} />);
    expect(screen.getByText(initials)).toBeInTheDocument();
  });

  it("is hidden from a screen reader beside the name, with the full name as its title", () => {
    render(<Avatar name="Mike Hansen" size="sm" />);
    const mark = screen.getByText("MH");
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark).toHaveAttribute("title", "Mike Hansen");
    expect(mark).toHaveClass("size-[22px]");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("is an image named by its label when one is passed", () => {
    render(<Avatar name="Mike Hansen" label="Owner: Mike Hansen" />);
    const mark = screen.getByRole("img", { name: "Owner: Mike Hansen" });
    expect(mark).not.toHaveAttribute("aria-hidden");
    expect(mark).toHaveClass("size-8");
  });
});
