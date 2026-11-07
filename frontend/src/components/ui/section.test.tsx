import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Section, SectionHeader } from "./section";

describe("Section", () => {
  it("is a region named by its heading, with the count and the trailing slot", () => {
    render(
      <Section title="Files" count={0} trailing={<button type="button">Add file</button>}>
        <p>Nothing here.</p>
      </Section>,
    );
    const region = screen.getByRole("region", { name: "Files 0" });
    expect(region).toHaveTextContent("Nothing here.");
    const heading = screen.getByRole("heading", { level: 3 });
    expect(heading).toHaveClass("uppercase", "tracking-label");
    expect(screen.getByRole("button", { name: "Add file" })).toBeInTheDocument();
  });

  it("is the bold sentence-case heading with size lg, at the level asked for", () => {
    render(
      <Section title="What will be done" size="lg" level={2}>
        <p>Steps</p>
      </Section>,
    );
    const heading = screen.getByRole("heading", { level: 2, name: "What will be done" });
    expect(heading).not.toHaveClass("uppercase");
    expect(heading).toHaveClass("text-base");
  });

  it("leaves the count out when none is given", () => {
    render(<SectionHeader title="Activity" />);
    expect(screen.getByRole("heading", { name: "Activity" }).children).toHaveLength(0);
  });
});
