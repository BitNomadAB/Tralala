import { expect, test } from "playwright/test";
import { approvedAnalysis, approveRoadmap, roadmap, ticketRow } from "./published-plan";
import {
  addCard,
  boardIdFromUrl,
  boardWithLoop,
  cardTile,
  closeDialog,
  csrfToken,
  login,
  loopAction,
  openCard,
  openPlanDocument,
  showTab,
  uniqueName,
} from "./support";

test.describe("loop planning and completion", () => {
  test("plans a Loop, publishes Tickets, completes work and finds it in history", async ({
    page,
  }) => {
    await login(page);
    const boardName = uniqueName("Loop journey");
    await boardWithLoop(page, boardName, "Email verification");
    const boardId = boardIdFromUrl(page);
    const loopId = page.url().split("/loops/")[1];

    // Info is written in the UI by a person.
    const infoDialog = await openPlanDocument(page, "Info");
    await infoDialog
      .getByLabel("Write or revise Info")
      .fill("Users must confirm their email address before signing in.");
    await infoDialog.getByRole("button", { name: "Save as new revision" }).click();
    await expect(infoDialog.getByText(/revision 1/)).toBeVisible();
    await showTab(page, "Kanban");

    const headers = { "X-CSRF-Token": await csrfToken(page) };
    const loopBase = `/api/v1/boards/${boardId}/loops/${loopId}`;

    const analysis = await page.request.post(`${loopBase}/candidates`, {
      headers,
      data: {
        kind: "analysis",
        analysis: {
          outcome: "Verify email addresses before sign-in",
          findings: [
            {
              id: "F-01",
              title: "Existing auth module can be reused",
              category: "reuse",
              technical_detail: "backend/app/services/auth.py",
              plain_language: "The sign-in code already exists and can be extended.",
            },
          ],
          assumptions: ["Users own a working address"],
          open_questions: ["Which provider?"],
          recommendation: "Choose a provider first.",
          verification: ["Unverified sign-in is rejected"],
        },
      },
    });
    expect(analysis.status()).toBe(201);

    // A person approves the analysis in the UI (reload: the candidate came through the API).
    await page.reload();
    const analysisDialog = await openPlanDocument(page, "Analysis");
    await expect(analysisDialog.getByText(/sign-in code already exists/)).toBeVisible();
    await analysisDialog.getByRole("button", { name: "Approve analysis" }).click();
    await expect(analysisDialog.getByRole("button", { name: "Approved" })).toBeVisible();
    await showTab(page, "Kanban");

    const plan = await page.request.post(`${loopBase}/candidates`, {
      headers,
      data: {
        kind: "roadmap",
        plan: {
          summary: "One phase",
          phases: [
            {
              id: crypto.randomUUID(),
              number: 1,
              name: "Database update",
              objective: "Store verification state",
              tickets: [
                {
                  id: crypto.randomUUID(),
                  title: "Add verification columns",
                  instructions: "Add the columns and a migration.",
                  acceptance_criteria: ["columns exist"],
                  summary: "The database remembers whether a sign-in address was verified.",
                  why: "Nothing records a verified address today. Without it every sign-in trusts the address.",
                  if_skipped:
                    "Unverified addresses keep signing in. The check has nowhere to store its result.",
                  pros: ["One place holds the verification state."],
                  cons: ["Existing accounts start as unverified."],
                  steps: [
                    "Add a verified mark and a verified date to every account.",
                    "Show the mark on the account page.",
                  ],
                },
              ],
            },
          ],
        },
      },
    });
    expect(plan.status()).toBe(201);

    await page.reload();
    const roadmapDialog = await openPlanDocument(page, "RoadMap");
    // The review shows each Phase as a section with a row per Ticket, and the approval counts them.
    const phase = roadmapDialog.getByRole("region", { name: /Database update/ });
    await expect(phase.getByText("Add verification columns")).toBeVisible();
    await roadmapDialog.getByRole("button", { name: /^Approve RoadMap/ }).click();
    await expect(roadmapDialog.getByText(/revision 1/).first()).toBeVisible();
    await showTab(page, "Kanban");

    // Publishing materialises the Ticket with its stable key.
    await page.reload();
    const ticket = page
      .getByRole("region", { name: /^Column / })
      .getByRole("listitem")
      .filter({ hasText: "Add verification columns" });
    await expect(ticket).toBeVisible();
    await expect(ticket).toContainText(/[A-Z]{2}\d{3}-/);

    await ticket.getByRole("button", { name: "Add verification columns", exact: true }).click();
    const cardDialog = page.getByRole("dialog", { name: "Add verification columns" });
    // In the first column the decision is Start work; Mark complete takes its place afterwards.
    await cardDialog.getByRole("button", { name: "Start work" }).click();
    await cardDialog.getByRole("button", { name: "Mark complete" }).click();
    await expect(cardDialog.getByRole("region", { name: "Status" })).toContainText("Completed");
    await expect(cardDialog.getByRole("button", { name: "Mark complete" })).toHaveCount(0);
    await page.getByRole("button", { name: "Close dialog" }).click();

    // Accept implementation together with a human QA attestation and finalize: the header's one
    // decision once every Ticket is done (its words follow the stage).
    await page.reload();
    await page.getByRole("button", { name: /^(Accept work|Finalize Loop)$/ }).click();
    const completion = page.getByRole("dialog", { name: /completion and QA/ });
    await completion.getByLabel("QA status").selectOption("passed");
    await completion.getByLabel("What was tested").fill("Manual smoke test");
    await completion.getByLabel("Results").fill("All checks passed");
    await completion.getByRole("button", { name: "Accept and complete the Loop" }).click();
    await expect(page.getByRole("dialog")).toContainText("is completed");
    await page.getByRole("button", { name: "Close dialog" }).click();
    await expect(page.getByText(/Read-only: this Loop is completed/)).toBeVisible();

    // The immutable snapshot is searchable in Board history.
    await page.getByRole("link", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Board history" })).toBeVisible();
    const record = page.getByRole("listitem").filter({ hasText: "Email verification" });
    await expect(record).toBeVisible();
    await record.getByRole("button").click();
    await expect(page.getByRole("dialog", { name: "Email verification" })).toBeVisible();
  });

  test("closes a Loop without the Tickets that are not done, and marks them Not done", async ({
    page,
  }) => {
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Unfinished journey");
    const plan = await page.request.post(candidates, {
      headers,
      data: roadmap(["Write the mail", "Send the link"]),
    });
    expect(plan.status()).toBe(201);
    await approveRoadmap(page, "Write the mail");

    // One Ticket is done, the other is never started.
    await ticketRow(page, "Write the mail")
      .getByRole("button", { name: "Write the mail", exact: true })
      .click();
    const cardDialog = page.getByRole("dialog", { name: "Write the mail" });
    await cardDialog.getByRole("button", { name: "Start work" }).click();
    await cardDialog.getByRole("button", { name: "Mark complete" }).click();
    await expect(cardDialog.getByRole("region", { name: "Status" })).toContainText("Completed");
    await page.getByRole("button", { name: "Close dialog" }).click();

    // The dialog names the Ticket that is not done and holds the acceptance up.
    await loopAction(page, "Finalize Loop");
    const completion = page.getByRole("dialog", { name: /completion and QA/ });
    await expect(completion.getByText("1 delivery Ticket is not done.")).toBeVisible();
    await expect(
      completion.getByRole("listitem").filter({ hasText: "Send the link" }),
    ).toBeVisible();
    await completion.getByLabel("QA status").selectOption("passed");
    await completion.getByLabel("What was tested").fill("Manual smoke test");
    await completion.getByLabel("Results").fill("All checks passed");
    const accept = completion.getByRole("button", { name: "Accept and complete the Loop" });
    await expect(accept).toHaveAttribute("aria-disabled", "true");

    // The person accepts without it, and the Loop is completed.
    await completion.getByRole("button", { name: "Accept without it" }).click();
    await expect(completion.getByText("Accepting without 1 delivery Ticket.")).toBeVisible();
    await accept.click();
    await expect(page.getByRole("dialog")).toContainText("is completed");
    await page.getByRole("button", { name: "Close dialog" }).click();
    await expect(page.getByText(/Read-only: this Loop is completed/)).toBeVisible();

    // The Ticket was not completed by that: it says Not done, and the other one says done.
    await expect(ticketRow(page, "Send the link")).toContainText("Not done");
    await expect(ticketRow(page, "Write the mail")).toContainText("done");
    await expect(ticketRow(page, "Write the mail")).not.toContainText("Not done");
  });

  test("runs a small change without a plan and closes it in one decision", async ({ page }) => {
    await login(page);
    const { boardId, loopId } = await boardWithLoop(page, uniqueName("Fast track"), "Fix a typo");
    const loop = await page.request.get(`/api/v1/boards/${boardId}/loops/${loopId}`);
    const loopKey = ((await loop.json()).data as { key: string }).key;

    // A Ticket in a new Loop starts it without a plan: no Info, analysis or RoadMap first.
    const title = "Correct the sign-in heading";
    await addCard(page, "Backlog", title);
    await expect(page.getByText("Without a plan", { exact: true })).toBeVisible();
    // The Ticket is the Loop's own work: keyed, and never marked as work outside a plan.
    await expect(cardTile(page, "Backlog", title)).toContainText(`${loopKey}-UNP-001`);
    await expect(cardTile(page, "Backlog", title)).not.toContainText("Unplanned");

    const ticket = await openCard(page, "Backlog", title);
    await ticket.getByRole("button", { name: "Start work" }).click();
    await ticket.getByRole("button", { name: "Mark complete" }).click();
    await expect(ticket.getByRole("region", { name: "Status" })).toContainText("Completed");
    await closeDialog(page);

    // With every Ticket done, the header's one decision closes the Loop, and no QA is asked for.
    await expect(page.getByText("Waits for you to close the Loop")).toBeVisible();
    await page.getByRole("button", { name: "Close Loop", exact: true }).click();
    const close = page.getByRole("dialog", { name: `Close ${loopKey}` });
    await expect(close).toContainText("One decision closes a Loop without a plan.");
    await close.getByRole("button", { name: "Close the Loop" }).click();
    await expect(page.getByText("Loop closed", { exact: true })).toBeVisible();
    await expect(page.getByRole("dialog", { name: `${loopKey} is completed` })).toBeVisible();
    await closeDialog(page);

    // Board history keeps it, marked as closed without a plan where a QA result would stand.
    await page.getByRole("link", { name: "History", exact: true }).click();
    const record = page.getByRole("listitem").filter({ hasText: "Fix a typo" });
    await expect(record.getByText("Closed without a plan", { exact: true })).toBeVisible();
    await expect(record).not.toContainText("QA not_run");
  });

  test("resets a scope, cleared draft or approved, so it can be generated again", async ({
    page,
  }) => {
    await login(page);
    const boardName = uniqueName("Reset journey");
    await boardWithLoop(page, boardName, "Session expiry");
    const boardId = boardIdFromUrl(page);
    const loopId = page.url().split("/loops/")[1];
    const loopBase = `/api/v1/boards/${boardId}/loops/${loopId}`;
    const headers = { "X-CSRF-Token": await csrfToken(page) };

    const infoDialog = await openPlanDocument(page, "Info");
    await infoDialog
      .getByLabel("Write or revise Info")
      .fill("Sessions must expire after 30 minutes of inactivity.");
    await infoDialog.getByRole("button", { name: "Save as new revision" }).click();
    await showTab(page, "Kanban");

    const candidate = {
      headers,
      data: {
        kind: "analysis",
        analysis: {
          outcome: "Expire idle sessions",
          findings: [
            {
              id: "F-01",
              title: "The session table has no expiry column",
              category: "change",
              technical_detail: "backend/app/services/auth.py",
              plain_language: "Sessions never time out today.",
            },
          ],
          assumptions: [],
          open_questions: [],
          recommendation: "Add an expiry column.",
          verification: ["An idle session is rejected"],
        },
      },
    };
    const analysis = await page.request.post(`${loopBase}/candidates`, candidate);
    expect(analysis.status()).toBe(201);

    // A draft that was never approved can be thrown away too: that is the way back from a bad run.
    await page.reload();
    const dialog = await openPlanDocument(page, "Analysis");
    await expect(dialog.getByText(/Sessions never time out today/)).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Reset analysis" })).toBeEnabled();
    await dialog.getByRole("button", { name: "Reset analysis" }).click();
    await expect(dialog.getByText(/Resetting clears the analysis/)).toBeVisible();
    await dialog.getByRole("button", { name: "Reset and clear" }).click();
    await expect(dialog.getByText("Nothing here yet.").first()).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Reset analysis" })).toHaveCount(0);

    // The same button clears an approved analysis, and asks first because the text is retired.
    expect((await page.request.post(`${loopBase}/candidates`, candidate)).status()).toBe(201);
    await page.reload();
    await openPlanDocument(page, "Analysis");
    await expect(dialog.getByText(/Sessions never time out today/)).toBeVisible();
    await dialog.getByRole("button", { name: "Approve analysis" }).click();
    await expect(dialog.getByRole("button", { name: "Approved" })).toBeVisible();
    await dialog.getByRole("button", { name: "Reset analysis" }).click();
    await expect(dialog.getByText(/Resetting clears the analysis/)).toBeVisible();
    await dialog.getByRole("button", { name: "Reset and clear" }).click();
    await expect(dialog.getByText("Nothing here yet.").first()).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Approve analysis" })).toBeVisible();

    // The Loop is back to needing an analysis before a RoadMap can be generated.
    const refused = await page.request.post(`${loopBase}/candidates`, {
      headers,
      data: {
        kind: "roadmap",
        plan: {
          summary: "Too early",
          phases: [
            {
              id: crypto.randomUUID(),
              number: 1,
              name: "Only phase",
              objective: "Prove the gate",
              tickets: [
                {
                  id: crypto.randomUUID(),
                  title: "A ticket",
                  instructions: "Do the work.",
                  acceptance_criteria: ["it works"],
                },
              ],
            },
          ],
        },
      },
    });
    expect(refused.status()).toBe(409);
    expect((await refused.json()).error.code).toBe("approval_required");
  });
});
