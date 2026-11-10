import { expect, test, type Locator, type Page } from "playwright/test";
import { blockingViolations } from "./axe";
import { mcpCall, mcpRefusal } from "./mcp";
import {
  boardIdFromUrl,
  closeDialog,
  createBoard,
  issueToken,
  listRegion,
  login,
  openPlanDocument,
  showTab,
  uniqueName,
} from "./support";
import * as tickets from "./ticket-plan";
import * as plan from "./worker-plan";

/**
 * A Ticket read the way its person reads it: a RoadMap with faces arrives over `/mcp`, the person
 * approves it, opens a Ticket over the Kanban, reads its steps and sections, writes a note, looks
 * at Raw text, opens the Ticket as a page and comes back, and starts the work.
 */

/** A Ticket's tile on the Loop's Kanban, whatever column it sits in. */
function tile(page: Page, title: string): Locator {
  return page
    .getByRole("region", { name: /^List / })
    .getByRole("listitem")
    .filter({ hasText: title });
}

/** Opens a Ticket over the Kanban from its tile; the dialog is named by the Ticket's title. */
async function openTicket(page: Page, title: string): Promise<Locator> {
  await tile(page, title).getByRole("button", { name: title, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog.getByRole("region", { name: "Status" })).toBeVisible();
  return dialog;
}

test.describe("the Ticket view", () => {
  test.use({ viewport: { width: 1600, height: 900 } });

  test("a person reads, notes, opens as a page and starts a planned Ticket", async ({
    page,
  }, testInfo) => {
    test.setTimeout(180_000);
    await login(page);
    const boardName = uniqueName("Ticket board");
    await createBoard(page, boardName);
    const boardId = boardIdFromUrl(page);
    const token = await issueToken(page, plan.WORKER_SCOPES);
    const call = (name: string, args: Record<string, unknown> = {}) =>
      mcpCall(page, token, name, args);
    const me = (await (await page.request.get("/api/v1/auth/me")).json()) as {
      data: { name: string };
    };
    const person = me.data.name;
    const loopName = uniqueName("Idle sessions");
    let loopId = "";
    let loopKey = "";

    await test.step("Info and an analysis with a brief arrive; the person approves", async () => {
      const created = await call("create_loop", {
        board_id: boardId,
        name: loopName,
        goal: "End idle sessions",
        idempotency_key: loopName,
      });
      const loop = created.loop as { id: string; key: string };
      loopId = loop.id;
      loopKey = loop.key;
      await call("write_info", { board_id: boardId, loop_id: loopId, content: plan.INFO });
      await call("write_analysis", {
        board_id: boardId,
        loop_id: loopId,
        analysis: plan.ANALYSIS,
        brief: plan.ANALYSIS_BRIEF,
      });
      await page.goto(`/boards/${boardId}/loops/${loopId}`);
      await expect(page.getByRole("heading", { name: loopName, level: 1 })).toBeVisible();
      const analysis = await openPlanDocument(page, "Analysis");
      await expect(analysis.getByText(plan.VERDICT_LINE)).toBeVisible();
      await analysis.getByRole("button", { name: "Approve analysis" }).click();
      await expect(analysis.getByRole("button", { name: "Approved" })).toBeVisible();
    });

    await test.step("a RoadMap whose step names a file is refused with the Ticket and the step", async () => {
      const refusal = await mcpRefusal(page, token, "write_roadmap", {
        board_id: boardId,
        loop_id: loopId,
        plan: tickets.roadmap([tickets.STEP_WITH_FILE, "Send it to everyone who signs in."]),
        brief: tickets.ROADMAP_BRIEF,
      });
      expect(refusal.code).toBe("face_invalid");
      expect(refusal.message).toContain("Ticket t2, steps[0]: looks like a file path (Banner.tsx)");
    });

    await test.step("the RoadMap with faces is reviewed by Phase and approved", async () => {
      await call("write_roadmap", {
        board_id: boardId,
        loop_id: loopId,
        plan: tickets.roadmap(),
        brief: tickets.ROADMAP_BRIEF,
      });
      await page.reload();
      const roadmap = await openPlanDocument(page, "RoadMap");
      await expect(roadmap.getByText(tickets.ROADMAP_GOAL)).toBeVisible();
      const first = roadmap.getByRole("region", { name: /^Phase 1 · Idle check/ });
      await first.getByText(tickets.FIVE_STEPS).click();
      await expect(first.getByRole("list", { name: "Steps" })).toBeVisible();
      await expect(first.getByRole("list", { name: "Steps" }).getByRole("listitem")).toHaveCount(5);
      const second = roadmap.getByRole("region", { name: /^Phase 2 · Roll-out/ });
      await second.getByText(tickets.TWO_STEPS).click();
      await expect(second.getByRole("list", { name: "Steps" }).getByRole("listitem")).toHaveCount(
        2,
      );
      expect(await blockingViolations(page, testInfo, "axe-roadmap-review")).toEqual([]);
      await roadmap.getByRole("button", { name: /^Approve RoadMap · 2 Tickets$/ }).click();
      await expect(roadmap.getByRole("button", { name: "Approved" })).toBeVisible();
      await showTab(page, "Kanban");
    });

    await test.step("the card shows the title and the summary; the modal shows the face", async () => {
      await page.reload();
      await expect(tile(page, tickets.FIVE_STEPS)).toContainText(tickets.FIVE_SUMMARY);
      await expect(tile(page, tickets.TWO_STEPS)).toContainText(tickets.TWO_SUMMARY);

      const dialog = await openTicket(page, tickets.FIVE_STEPS);
      const key = new RegExp(`^${loopKey}-[A-Z0-9]{2}\\d{2,}-\\d{3}$`);
      await expect(dialog.getByText(key).first()).toBeVisible();
      await expect(dialog.getByText(/^Phase 1 · /)).toBeVisible();
      await expect(
        dialog.getByRole("heading", { name: tickets.FIVE_STEPS, level: 2 }),
      ).toBeVisible();
      const you = dialog.getByRole("tabpanel", { name: "For you" });
      await expect(you.getByRole("list", { name: "Steps" }).getByRole("listitem")).toHaveCount(5);
      await expect(you.getByText(tickets.STEPS[4] ?? "")).toBeVisible();
      await you.getByText("Why it is needed", { exact: true }).click();
      await expect(you.getByText(tickets.WHY)).toBeVisible();
      await you.getByText("If we skip it", { exact: true }).click();
      await expect(you.getByText(tickets.IF_SKIPPED)).toBeVisible();
      await you.getByText(/^Pro and con\d/).click();
      await expect(you.getByRole("list", { name: "For" })).toContainText(tickets.PRO);
      await expect(you.getByRole("list", { name: "Against" })).toContainText(tickets.CON);
      // The agent's own text is not in For you.
      await expect(you.getByText(tickets.CRITERION)).toHaveCount(0);

      await dialog.getByRole("tab", { name: "Raw text" }).click();
      const raw = dialog.getByRole("tabpanel", { name: "Raw text" });
      await expect(raw.getByRole("heading", { name: "Accepted when" })).toBeVisible();
      await expect(raw.getByText(tickets.CRITERION).first()).toBeVisible();
      await dialog.getByRole("tab", { name: "For you" }).click();
      expect(await blockingViolations(page, testInfo, "axe-ticket-modal")).toEqual([]);
    });

    await test.step("the person adds a note, edits it and sees author and date", async () => {
      const dialog = page.getByRole("dialog", { name: tickets.FIVE_STEPS });
      await dialog.getByText(/^Your notes\d/).click();
      await dialog.getByLabel("Add a note", { exact: true }).fill(tickets.NOTE);
      await dialog.getByRole("button", { name: "Save note" }).click();
      const notes = dialog.getByRole("list", { name: "Your notes" });
      await expect(notes).toContainText(tickets.NOTE);
      await notes.getByRole("button", { name: "Edit" }).click();
      await notes.getByLabel("Edit the note").fill(tickets.NOTE_EDITED);
      await notes.getByRole("button", { name: "Save", exact: true }).click();
      await expect(notes.getByText(tickets.NOTE_EDITED)).toBeVisible();
      await expect(notes.getByText(tickets.NOTE, { exact: true })).toHaveCount(0);
      // The author line: the person's name and the date it was written.
      await expect(notes.getByText(new RegExp(`^${person} · \\S`))).toBeVisible();
    });

    await test.step("Open as page shows the same Ticket; Back to the board returns", async () => {
      const dialog = page.getByRole("dialog", { name: tickets.FIVE_STEPS });
      await dialog.getByRole("button", { name: "Open as page" }).click();
      await expect(page).toHaveURL(
        new RegExp(`/boards/${boardId}/loops/${loopId}/tickets/[0-9a-f-]{36}$`),
      );
      await expect(page.getByRole("dialog")).toHaveCount(0);
      const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
      await expect(crumbs.getByRole("link", { name: boardName })).toBeVisible();
      await expect(crumbs.getByRole("link", { name: `${loopKey} ${loopName}` })).toBeVisible();
      await expect(crumbs.getByText("Phase 1 · Idle check")).toBeVisible();
      await expect(crumbs.getByText(new RegExp(`^${loopKey}-`))).toBeVisible();
      await expect(page.getByRole("heading", { name: tickets.FIVE_STEPS, level: 1 })).toBeVisible();
      await expect(page.getByRole("list", { name: "Steps" }).getByRole("listitem")).toHaveCount(5);
      await expect(page.getByRole("list", { name: "Your notes" })).toContainText(
        tickets.NOTE_EDITED,
      );
      expect(await blockingViolations(page, testInfo, "axe-ticket-page")).toEqual([]);

      await page.getByRole("link", { name: "Back to the board" }).click();
      await expect(page).toHaveURL(new RegExp(`/boards/${boardId}/loops/${loopId}`));
      await expect(page.getByRole("heading", { name: loopName, level: 1 })).toBeVisible();
      await expect(tile(page, tickets.FIVE_STEPS)).toBeVisible();
    });

    await test.step("Start work moves the Ticket to the next column and assigns the person", async () => {
      const dialog = await openTicket(page, tickets.FIVE_STEPS);
      const status = dialog.getByRole("region", { name: "Status" });
      await expect(status.getByRole("button", { name: "Column: Backlog" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Owner: None" })).toBeVisible();
      await dialog.getByRole("button", { name: "Start work" }).click();
      await expect(status.getByRole("button", { name: "Column: Todo" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: `Owner: ${person}` })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Start work" })).toHaveCount(0);
      await closeDialog(page);
      await expect(listRegion(page, "Todo").getByRole("listitem")).toContainText(
        tickets.FIVE_STEPS,
      );
    });

    await test.step("a Ticket written without a face shows its description", async () => {
      await call("create_ticket", {
        board_id: boardId,
        loop_id: loopId,
        title: tickets.UNPLANNED,
        description: tickets.UNPLANNED_TEXT,
        workplace: "codebase",
      });
      await page.reload();
      const dialog = await openTicket(page, tickets.UNPLANNED);
      const you = dialog.getByRole("tabpanel", { name: "For you" });
      await expect(you.getByText(tickets.UNPLANNED_TEXT)).toBeVisible();
      await expect(you.getByText("Written before Tickets had a plain summary.")).toBeVisible();
      await expect(you.getByRole("list", { name: "Steps" })).toHaveCount(0);
      await expect(you.getByLabel("Add a note", { exact: true })).toBeVisible();
      await closeDialog(page);
    });

    await test.step("the board page has no serious or critical axe violation", async () => {
      await page.goto(`/boards/${boardId}`);
      await expect(page.getByRole("heading", { name: boardName, level: 1 })).toBeVisible();
      await expect(page.getByRole("list", { name: "Current Loops" })).toContainText(loopName);
      expect(await blockingViolations(page, testInfo, "axe-board-page")).toEqual([]);
    });
  });
});
