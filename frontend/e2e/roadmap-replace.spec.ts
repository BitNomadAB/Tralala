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

test.describe("a RoadMap written again", () => {
  test("replaces the earlier plan's untouched Tickets and keeps the started one", async ({
    page,
  }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Replace plan"), "Address check");
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

    // The first plan is approved and its two Tickets are published.
    const first = await page.request.post(candidates, {
      headers,
      data: roadmap(["Write the mail", "Send the link"]),
    });
    expect(first.status()).toBe(201);
    await approveRoadmap(page, "Write the mail");
    await expect(ticketRow(page, "Write the mail")).toBeVisible();

    // Somebody starts one of them; the other stays untouched.
    await ticketRow(page, "Send the link")
      .getByRole("button", { name: /Send the link/ })
      .click();
    const cardDialog = page.getByRole("dialog", { name: "Send the link" });
    await cardDialog.getByRole("button", { name: "Start work" }).click();
    await expect(cardDialog.getByRole("button", { name: "Mark complete" })).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();

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
});
