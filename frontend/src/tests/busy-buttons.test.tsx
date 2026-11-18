import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it } from "vitest";
import { BriefApprove } from "@/features/loops/BriefApprove";
import { InfoEditor } from "@/features/loops/InfoEditor";
import { ScopeReview } from "@/features/loops/ScopeReview";

type ReviewProps = ComponentProps<typeof ScopeReview>;

function review(props: Partial<ReviewProps>) {
  const base: ReviewProps = {
    scopeLabel: "RoadMap",
    isHuman: true,
    readOnly: false,
    feedback: "",
    onFeedbackChange: () => undefined,
    canReset: false,
    confirmReset: false,
    onConfirmResetChange: () => undefined,
    resetPending: false,
    onReset: () => undefined,
    canReview: true,
    approved: false,
    reviewPending: false,
    onDecision: () => undefined,
    onRegenerate: () => undefined,
  };
  return <ScopeReview {...base} {...props} />;
}

describe("the decision on a scope", () => {
  it("keeps the focus on Approve while it is recorded and once it reads Approved", async () => {
    const { rerender } = render(review({}));
    await userEvent.setup().click(screen.getByRole("button", { name: "Approve RoadMap" }));
    rerender(review({ reviewPending: true }));
    const approve = screen.getByRole("button", { name: "Approve RoadMap" });
    expect(approve).toHaveFocus();
    expect(approve).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: "Request changes" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );

    rerender(review({ approved: true }));
    expect(screen.getByRole("button", { name: "Approved" })).toHaveFocus();
  });

  it("keeps the focus on Regenerate while the new run starts, unless it could not start one", () => {
    render(review({ regenerateBusy: true }));
    expect(screen.getByRole("button", { name: /Regenerate RoadMap/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    render(review({ regenerateBusy: true, regenerateDisabled: true, scopeLabel: "analysis" }));
    expect(screen.getByRole("button", { name: /Regenerate analysis/ })).toBeDisabled();
  });

  it("keeps the brief's Approve analysis focusable while it is recorded", () => {
    const approval = {
      revisionNumber: 2,
      technicalRevisionNumber: 1,
      approved: false,
      disabled: false,
      pending: true,
      onApprove: () => undefined,
    };
    const { rerender } = render(<BriefApprove approval={approval} />);
    expect(screen.getByRole("button", { name: "Approve analysis" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    rerender(<BriefApprove approval={{ ...approval, pending: false, disabled: true }} />);
    expect(screen.getByRole("button", { name: "Approve analysis" })).toBeDisabled();
  });
});

function editor(props: Partial<ComponentProps<typeof InfoEditor>>) {
  return (
    <InfoEditor
      value="Sessions expire."
      onChange={() => undefined}
      isHuman
      readOnly={false}
      saving={false}
      changed
      onSave={() => undefined}
      {...props}
    />
  );
}

describe("Save as new revision", () => {
  it("says why it cannot save instead of turning disabled", () => {
    const { rerender } = render(editor({ changed: false }));
    const name = "Save as new revision";
    expect(screen.getByRole("button", { name, description: "No changes to save" })).toBeEnabled();
    rerender(editor({ saving: true }));
    expect(screen.getByRole("button", { name, description: "Saving…" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    rerender(editor({}));
    expect(screen.getByRole("button", { name })).not.toHaveAttribute("aria-disabled");
  });

  it("stays disabled for a reader who cannot save at all", () => {
    render(editor({ isHuman: false }));
    expect(screen.getByRole("button", { name: "Save as new revision" })).toBeDisabled();
  });
});
