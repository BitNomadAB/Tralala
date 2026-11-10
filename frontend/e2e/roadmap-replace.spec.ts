import { expect, test, type Locator, type Page } from "playwright/test";
import {
  boardIdFromUrl,
  boardWithLoop,
  csrfToken,
  login,
  openPlanDocument,
  showTab,
  uniqueName,
} from "./support";

/** A RoadMap candidate with one Phase and a Ticket per title, every identity new. */
function roadmap(titles: string[]) {
  return {
    kind: "roadmap",
    plan: {
      summary: "One phase",
      phases: [
        {
          id: crypto.randomUUID(),
          number: 1,
          name: "Mail check",
          objective: "Addresses are confirmed",
          tickets: titles.map((title) => ({
            id: crypto.randomUUID(),
            title,
            instructions: "Do the step and note what changed.",
            acceptance_criteria: ["the step is done"],
            summary: "A step of the address check.",
            why: "The address check needs this step.",
            if_skipped: "The address check stays unfinished.",
            pros: ["The check moves forward."],
            cons: ["It takes an afternoon."],
            steps: ["Do the step.", "Tell the team it is done."],
          })),
        },
      ],
    },
  };
}

function ticketRow(page: Page, title: string): Locator {
  return page
    .getByRole("region", { name: /^List / })
    .getByRole("listitem")
    .filter({ hasText: title });
}

async function approveRoadmap(page: Page, title: string): Promise<void> {
  await page.reload();
  const roadmapDialog = await openPlanDocument(page, "RoadMap");
  await expect(roadmapDialog.getByText(title)).toBeVisible();
  await roadmapDialog.getByRole("button", { name: /^Approve RoadMap/ }).click();
  await expect(roadmapDialog.getByRole("button", { name: "Approved" })).toBeVisible();
  await showTab(page, "Kanban");
  await page.reload();
}

/** A new board whose Loop has Info and an approved analysis; answers where its candidates go. */
async function approvedAnalysis(
  page: Page,
  board: string,
): Promise<{ candidates: string; headers: Record<string, string> }> {
  await boardWithLoop(page, uniqueName(board), "Address check");
  const boardId = boardIdFromUrl(page);
  const loopId = page.url().split("/loops/")[1];

  const infoDialog = await openPlanDocument(page, "Info");
  await infoDialog.getByLabel("Write or revise Info").fill("People confirm their address.");
  await infoDialog.getByRole("button", { name: "Save as new revision" }).click();
  await expect(infoDialog.getByText(/revision 1/)).toBeVisible();

  const headers = { "X-CSRF-Token": await csrfToken(page) };
  const candidates = `/api/v1/boards/${boardId}/loops/${loopId}/candidates`;
  const analysis = await page.request.post(candidates, {
    headers,
    data: {
      kind: "analysis",
      analysis: {
        outcome: "Confirm addresses",
        findings: [
          {
            id: "F-01",
            title: "The sign-in can send mail",
            category: "reuse",
            technical_detail: "The mailer exists.",
            plain_language: "The sign-in can already send mail.",
          },
        ],
        recommendation: "Go ahead.",
      },
    },
  });
  expect(analysis.status()).toBe(201);
  await page.reload();
  const analysisDialog = await openPlanDocument(page, "Analysis");
  await analysisDialog.getByRole("button", { name: "Approve analysis" }).click();
  await expect(analysisDialog.getByRole("button", { name: "Approved" })).toBeVisible();
  return { candidates, headers };
}

/** Somebody starts the Ticket, so it is no longer untouched. */
async function startTicket(page: Page, title: string): Promise<void> {
  await ticketRow(page, title)
    .getByRole("button", { name: new RegExp(title) })
    .click();
  const cardDialog = page.getByRole("dialog", { name: title });
  await cardDialog.getByRole("button", { name: "Start work" }).click();
  await expect(cardDialog.getByRole("button", { name: "Mark complete" })).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
}

test.describe("a RoadMap written again", () => {
  test("replaces the earlier plan's untouched Tickets and keeps the started one", async ({
    page,
  }) => {
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Replace plan");

    // The first plan is approved and its two Tickets are published.
    const first = await page.request.post(candidates, {
      headers,
      data: roadmap(["Write the mail", "Send the link"]),
    });
    expect(first.status()).toBe(201);
    await approveRoadmap(page, "Write the mail");
    await expect(ticketRow(page, "Write the mail")).toBeVisible();

    // Somebody starts one of them; the other stays untouched.
    await startTicket(page, "Send the link");

    // The RoadMap is written again with new Tickets and approved: the untouched Ticket of the
    // first plan is gone, the started one stays beside the new one.
    const second = await page.request.post(candidates, {
      headers,
      data: roadmap(["Confirm the address"]),
    });
    expect(second.status()).toBe(201);
    await approveRoadmap(page, "Confirm the address");
    await expect(ticketRow(page, "Confirm the address")).toBeVisible();
    await expect(ticketRow(page, "Send the link")).toBeVisible();
    await expect(ticketRow(page, "Write the mail")).toHaveCount(0);
  });

  test("a RoadMap reset takes every Ticket of the plan off the Kanban", async ({ page }) => {
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Reset plan");
    const plan = await page.request.post(candidates, {
      headers,
      data: roadmap(["Write the mail", "Send the link"]),
    });
    expect(plan.status()).toBe(201);
    await approveRoadmap(page, "Write the mail");
    await startTicket(page, "Send the link");

    // The reset says what it does to the Tickets before it does it.
    const roadmapDialog = await openPlanDocument(page, "RoadMap");
    await roadmapDialog.getByRole("button", { name: "Reset RoadMap" }).click();
    await expect(roadmapDialog.getByText(/Its 2 Tickets leave the Kanban/)).toBeVisible();
    await roadmapDialog.getByRole("button", { name: "Reset and clear" }).click();
    await expect(roadmapDialog.getByRole("button", { name: "Reset RoadMap" })).toHaveCount(0);

    // The untouched Ticket is deleted and the started one archived: neither is on the Kanban.
    await showTab(page, "Kanban");
    await expect(page.getByRole("region", { name: /^List / }).first()).toBeVisible();
    await expect(ticketRow(page, "Write the mail")).toHaveCount(0);
    await expect(ticketRow(page, "Send the link")).toHaveCount(0);
  });
});
