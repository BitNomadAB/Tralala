import { expect, test } from "playwright/test";
import { boardIdFromUrl, boardWithLoop, csrfToken, login, uniqueName } from "./support";

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
    await page.getByRole("button", { name: /^Info/ }).click();
    const infoDialog = page.getByRole("dialog", { name: /planning documents/ });
    await infoDialog
      .getByLabel("Write or revise Info")
      .fill("Users must confirm their email address before signing in.");
    await infoDialog.getByRole("button", { name: "Save as new revision" }).click();
    await expect(infoDialog.getByText(/revision 1/)).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();

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
    await page.getByRole("button", { name: "Analysis" }).click();
    const analysisDialog = page.getByRole("dialog", { name: /planning documents/ });
    await expect(analysisDialog.getByText(/sign-in code already exists/)).toBeVisible();
    await analysisDialog.getByRole("button", { name: "Approve analysis" }).click();
    await expect(analysisDialog.getByRole("button", { name: "Approved" })).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();

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
                },
              ],
            },
          ],
        },
      },
    });
    expect(plan.status()).toBe(201);

    await page.reload();
    await page.getByRole("button", { name: "RoadMap" }).click();
    const roadmapDialog = page.getByRole("dialog", { name: /planning documents/ });
    await expect(roadmapDialog.getByText(/Database update/)).toBeVisible();
    await roadmapDialog.getByRole("button", { name: "Approve RoadMap" }).click();
    await expect(roadmapDialog.getByText(/revision 1/).first()).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();

    // Publishing materialises the Ticket with its stable key.
    await page.reload();
    const ticket = page
      .getByRole("region", { name: /^List / })
      .getByRole("listitem")
      .filter({ hasText: "Add verification columns" });
    await expect(ticket).toBeVisible();
    await expect(ticket).toContainText(/[A-Z]{2}\d{3}-/);

    await ticket.getByRole("button", { name: /Add verification columns/ }).click();
    const cardDialog = page.getByRole("dialog");
    await cardDialog.getByRole("button", { name: "Mark complete" }).click();
    await expect(cardDialog.getByRole("button", { name: "Mark incomplete" })).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();

    // Accept implementation together with a human QA attestation and finalize.
    await page.getByRole("button", { name: "Complete & QA" }).click();
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

    await page.getByRole("button", { name: /^Info/ }).click();
    const infoDialog = page.getByRole("dialog", { name: /planning documents/ });
    await infoDialog
      .getByLabel("Write or revise Info")
      .fill("Sessions must expire after 30 minutes of inactivity.");
    await infoDialog.getByRole("button", { name: "Save as new revision" }).click();
    await page.getByRole("button", { name: "Close dialog" }).click();

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
    await page.getByRole("button", { name: "Analysis" }).click();
    const dialog = page.getByRole("dialog", { name: /planning documents/ });
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
    await page.getByRole("button", { name: "Analysis" }).click();
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
