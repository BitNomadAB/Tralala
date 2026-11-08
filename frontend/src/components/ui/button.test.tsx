import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./button";

describe("Button", () => {
  it("is a plain button by default, so it never submits a form by accident", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("type", "button");
  });

  it("draws the quiet variant without a border colour or a background of its own", () => {
    render(
      <Button variant="quiet" aria-label="More actions">
        …
      </Button>,
    );
    const button = screen.getByRole("button", { name: "More actions" });
    expect(button).toHaveClass("border-transparent", "bg-transparent");
    expect(button).toHaveClass("text-[var(--muted-foreground)]");
  });

  it("draws the quiet danger variant in the danger colour without a fill", () => {
    render(<Button variant="danger-quiet">Stop</Button>);
    const button = screen.getByRole("button", { name: "Stop" });
    expect(button).toHaveClass("border-transparent", "bg-transparent");
    expect(button).toHaveClass("text-[var(--destructive)]");
  });
});
