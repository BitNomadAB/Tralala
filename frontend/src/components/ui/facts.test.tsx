import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Fact, Facts } from "./facts";

describe("Facts", () => {
  it("is a description list with one term and one value per fact", () => {
    render(
      <Facts>
        <Fact label="Owner">Mike</Fact>
        <Fact label="Due" none>
          ignored
        </Fact>
      </Facts>,
    );
    const terms = screen.getAllByRole("term");
    const values = screen.getAllByRole("definition");
    expect(terms.map((term) => term.textContent)).toEqual(["Owner", "Due"]);
    expect(values.map((value) => value.textContent)).toEqual(["Mike", "None"]);
    expect(within(values[1] ?? document.body).getByText("None")).toHaveClass(
      "text-[var(--foreground-faint)]",
    );
    expect(values[0]).not.toHaveClass("text-[var(--foreground-faint)]");
  });
});
