import { expect, type Locator, type Page } from "playwright/test";
import {
  boardIdFromUrl,
  boardWithLoop,
  csrfToken,
  openPlanDocument,
  showTab,
  uniqueName,
} from "./support";

/**
 * A Loop with a published plan, for the journeys that start from its Tickets: Info and an approved
 * analysis (`approvedAnalysis`), a RoadMap candidate of one Phase (`roadmap`), its approval in the
 * UI (`approveRoadmap`), and a Ticket on the Kanban (`ticketRow`, `startTicket`).
 */

/** A RoadMap candidate with one Phase and a Ticket per title, every identity new. */
export function roadmap(titles: string[]) {
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

export function ticketRow(page: Page, title: string): Locator {
  return page
    .getByRole("region", { name: /^Column / })
    .getByRole("listitem")
    .filter({ hasText: title });
}

export async function approveRoadmap(page: Page, title: string): Promise<void> {
  await page.reload();
  const roadmapDialog = await openPlanDocument(page, "RoadMap");
  await expect(roadmapDialog.getByText(title)).toBeVisible();
  await roadmapDialog.getByRole("button", { name: /^Approve RoadMap/ }).click();
  await expect(roadmapDialog.getByRole("button", { name: "Approved" })).toBeVisible();
  await showTab(page, "Kanban");
  await page.reload();
}

/** Where a Loop's candidates go, the CSRF header a person's request sends, and the ids. */
export interface LoopUnderReview {
  boardId: string;
  loopId: string;
  candidates: string;
  headers: Record<string, string>;
}

/** A new board whose Loop has Info and an analysis that waits for a person's review. */
export async function analysisUnderReview(page: Page, board: string): Promise<LoopUnderReview> {
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
  return { boardId, loopId: loopId ?? "", candidates, headers };
}

/** A new board whose Loop has Info and an approved analysis; answers where its candidates go. */
export async function approvedAnalysis(
  page: Page,
  board: string,
): Promise<{ candidates: string; headers: Record<string, string> }> {
  const { candidates, headers } = await analysisUnderReview(page, board);
  await page.reload();
  const analysisDialog = await openPlanDocument(page, "Analysis");
  await analysisDialog.getByRole("button", { name: "Approve analysis" }).click();
  await expect(analysisDialog.getByRole("button", { name: "Approved" })).toBeVisible();
  return { candidates, headers };
}

/** Somebody starts the Ticket, so it is no longer untouched. */
export async function startTicket(page: Page, title: string): Promise<void> {
  await ticketRow(page, title).getByRole("button", { name: title, exact: true }).click();
  const cardDialog = page.getByRole("dialog", { name: title });
  await cardDialog.getByRole("button", { name: "Start work" }).click();
  await expect(cardDialog.getByRole("button", { name: "Mark complete" })).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
}
