import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { rewriteBlockedReason } from "@/features/loops/loopUi";
import { generationRun } from "./msw/loops";
import {
  briefDocuments,
  EARLIER_ROADMAP_BRIEF,
  openBrief as open,
  ROADMAP_GOAL,
} from "./renderBrief";

describe("the brief for people", () => {
  it("names who wrote the analysis brief and never shows an id", async () => {
    open(briefDocuments());
    expect(await screen.findByText("Yes, with conditions")).toBeInTheDocument();
    expect(screen.getByText("Written by Coder")).toBeInTheDocument();
    const forYou = within(screen.getByRole("tabpanel", { name: "For you" }));
    expect(forYou.queryByText(/F-0/)).not.toBeInTheDocument();
  });

  it("switches between the brief for people and the version for AI", async () => {
    open(briefDocuments());
    const user = userEvent.setup();
    expect(await screen.findByRole("button", { name: "For people" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "For AI" }));
    expect(screen.getByText("Analysis (AI)")).toBeInTheDocument();
    expect(screen.queryByText("Yes, with conditions")).not.toBeInTheDocument();
    // Without the brief on screen the review carries the approval again.
    expect(screen.getByRole("button", { name: "Approve analysis" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "For people" }));
    expect(screen.getByText("Yes, with conditions")).toBeInTheDocument();
  });

  it("shows the RoadMap brief as its goal and the number of Tickets, nothing more", async () => {
    open(briefDocuments(), "roadmap");
    expect(await screen.findByText(ROADMAP_GOAL)).toBeInTheDocument();
    expect(screen.getByText("1 Ticket")).toBeInTheDocument();
    // The Phases and Tickets follow it from the plan; the brief repeats none of them.
    expect(screen.queryByRole("heading", { name: "The order of work" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Your part" })).not.toBeInTheDocument();
    expect(screen.getByText("Written by Planner")).toBeInTheDocument();
    expect(screen.queryByText("Earlier format")).not.toBeInTheDocument();
  });

  it("shows a RoadMap brief written before the goal by its summary alone", async () => {
    const documents = briefDocuments();
    open(
      { ...documents, roadmap: { ...documents.roadmap, current_payload: EARLIER_ROADMAP_BRIEF } },
      "roadmap",
    );
    expect(await screen.findByText("Two Phases: the e-mail, then the policy.")).toBeInTheDocument();
    expect(screen.queryByText("Sign the retention policy.")).not.toBeInTheDocument();
    expect(screen.getByText("1 Ticket")).toBeInTheDocument();
    expect(screen.queryByText("Earlier format")).not.toBeInTheDocument();
  });

  it("labels a view written before briefs as the earlier format", async () => {
    open(
      briefDocuments({
        current_payload: null,
        current_content: "People confirm by e-mail [F-02].",
        current_provenance: { written: true, agent_name: "Alpha" },
      }),
    );
    expect(await screen.findByText("Earlier format")).toBeInTheDocument();
    expect(screen.getByText("People confirm by e-mail [F-02].")).toBeInTheDocument();
  });

  it("says why it cannot be rewritten for people", async () => {
    open(briefDocuments({ state: "approved" }));
    expect(
      await screen.findByText("Approved: request changes or reset to rewrite"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rewrite for people/ })).toBeDisabled();
  });

  it("says that a brief is being written while its run is on", async () => {
    open(briefDocuments(), "roadmap", [
      generationRun("running", "writing_for_people", { id: "run-7", purpose: "roadmap_human" }),
    ]);
    expect(await screen.findByText("Writing for people...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rewrite for people/ })).toBeDisabled();
    // The approval counts the Tickets it publishes ("Approve RoadMap · 1 Ticket").
    expect(screen.getByRole("button", { name: /^Approve RoadMap/ })).toBeDisabled();
  });

  it("names the reasons in the order a person meets them", () => {
    const base = { approved: false, writing: false, generating: false, hasTechnical: true };
    expect(rewriteBlockedReason(base)).toBeNull();
    expect(rewriteBlockedReason({ ...base, approved: true, writing: true })).toBe(
      "Writing for people...",
    );
    expect(rewriteBlockedReason({ ...base, hasTechnical: false })).toBe(
      "Generate the technical version first",
    );
  });
});
