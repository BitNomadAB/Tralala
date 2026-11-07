import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState } from "./empty-state";

describe("EmptyState", () => {
  it("says one line", () => {
    const { container } = render(<EmptyState message="No comments yet." />);
    expect(screen.getByText("No comments yet.")).toBeInTheDocument();
    expect(container.querySelectorAll("p")).toHaveLength(1);
  });

  it("adds the small line under it", () => {
    const { container } = render(
      <EmptyState message="No work recorded yet." detail="A session's summaries appear here." />,
    );
    expect(screen.getByText("A session's summaries appear here.")).toHaveClass("text-xs");
    expect(container.querySelectorAll("p")).toHaveLength(2);
  });
});
