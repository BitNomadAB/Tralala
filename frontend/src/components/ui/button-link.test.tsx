import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Button } from "./button";
import { ButtonLink } from "./button-link";

describe("ButtonLink", () => {
  it("is a link that looks exactly like the Button of the same variant and size", () => {
    render(
      <MemoryRouter>
        <Button variant="secondary" size="sm">
          Save
        </Button>
        <ButtonLink to="/settings/agents/new" variant="secondary" size="sm">
          New agent
        </ButtonLink>
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "New agent" });
    expect(link).toHaveAttribute("href", "/settings/agents/new");
    expect(link.className).toBe(screen.getByRole("button", { name: "Save" }).className);
  });

  it("draws the quiet way back above an editor without a button's size", () => {
    render(
      <MemoryRouter>
        <ButtonLink to="/settings" variant="back" size="none">
          Settings
        </ButtonLink>
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Settings" });
    expect(link).toHaveClass("text-xs", "hover:underline");
    expect(link).not.toHaveClass("text-sm", "h-8", "h-9");
  });
});
