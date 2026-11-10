import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InfoEditor } from "@/features/loops/InfoEditor";

function renderEditor(isHuman: boolean) {
  return render(
    <InfoEditor
      value=""
      onChange={() => undefined}
      isHuman={isHuman}
      readOnly={false}
      canSave={isHuman}
      onSave={() => undefined}
    />,
  );
}

describe("InfoEditor copy", () => {
  it("tells a person that a coding agent may write Info while the Loop is speculative", () => {
    renderEditor(true);
    const field = screen.getByLabelText("Write or revise Info");
    expect(field).toBeEnabled();
    expect(field).toHaveAttribute(
      "placeholder",
      "The goal: what should be true when this Loop is done. Then requirements, constraints and links.",
    );
    expect(
      screen.getByText(
        /A coding agent may also write it through write_info while the Loop is a draft/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/once planning has started, only a person changes it/)).toBeVisible();
  });

  it("never says that agents cannot write Info", () => {
    const { container } = renderEditor(false);
    expect(screen.getByLabelText("Write or revise Info")).toBeDisabled();
    expect(
      screen.getByText(/A coding agent writes Info through write_info while the Loop is a draft/),
    ).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/cannot write Info/i);
    expect(container.innerHTML).not.toMatch(/Only a person can edit this/);
  });
});
