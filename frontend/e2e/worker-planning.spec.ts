import { expect, test, type Locator, type Page } from "playwright/test";
import { blockingViolations } from "./axe";
import { mcpCall, mcpToolNames, rowsOf } from "./mcp";
import { boardIdFromUrl, closeDialog, createBoard, issueToken, login, uniqueName } from "./support";
import * as plan from "./worker-plan";

/**
 * The shared workspace as `/llms.txt` section 3 describes it: a worker key starts a Loop over
 * `/mcp`, a person approves its analysis and RoadMap in the UI, and the worker then works the
 * published Tickets. Every write is read back from the UI, never from the API alone.
 */

/** A Ticket's tile on the Loop's Kanban, whatever column it sits in. */
function tile(page: Page, title: string): Locator {
  return page
    .getByRole("region", { name: /^List / })
    .getByRole("listitem")
    .filter({ hasText: title });
}

/** Opens a Ticket's dialog from a freshly loaded Kanban. */
async function openTicket(page: Page, title: string): Promise<Locator> {
  await page.reload();
  await tile(page, title)
    .getByRole("button", { name: new RegExp(title) })
    .click();
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog.getByRole("region", { name: "Status" })).toBeVisible();
  return dialog;
}

/** Opens one of the Loop's planning documents from a freshly loaded Loop page. */
async function openDocument(page: Page, name: "Info" | "Analysis" | "RoadMap"): Promise<Locator> {
  await page.reload();
  await page.getByRole("button", { name: new RegExp(`^${name}`) }).click();
  return page.getByRole("dialog", { name: /planning documents/ });
}

test.describe("the planning journey over /mcp", () => {
  // The side panels and the toolbar fit on one line only on a wide window.
  test.use({ viewport: { width: 1600, height: 900 } });

  test("a worker key plans a Loop with a person and works its Tickets", async ({
    page,
  }, testInfo) => {
    test.setTimeout(240_000);
    await login(page);
    const boardName = uniqueName("Worker board");
    await createBoard(page, boardName);
    const token = await issueToken(page, plan.WORKER_SCOPES);
    const call = (name: string, args: Record<string, unknown> = {}) =>
      mcpCall(page, token, name, args);
    const boardId = boardIdFromUrl(page);
    const loopName = uniqueName("Idle sessions");
    let loopId = "";
    let loopKey = "";
    const ids: Record<string, string> = {};

    await test.step("the key sees its tools, its scopes and the person's board", async () => {
      const tools = await mcpToolNames(page, token);
      expect(tools).toContain("write_analysis");
      expect(tools).toContain("set_ticket_wait");
      const whoami = await call("whoami");
      expect(whoami.scopes).toEqual([...plan.WORKER_SCOPES].sort());
      const boards = rowsOf<{ id: string; name: string }>(await call("list_boards"), "boards");
      expect(boards.find((board) => board.name === boardName)?.id).toBe(boardId);
    });

    await test.step("create_loop shows under Current Loops, write_info on the Loop page", async () => {
      const created = await call("create_loop", {
        board_id: boardId,
        name: loopName,
        goal: "End idle sessions",
        idempotency_key: loopName,
      });
      const loop = created.loop as { id: string; key: string };
      loopId = loop.id;
      loopKey = loop.key;
      await page.reload();
      await expect(page.getByRole("heading", { name: "Current Loops" })).toBeVisible();
      await page.getByRole("link", { name: new RegExp(loopName) }).click();
      await expect(page.getByRole("heading", { name: loopName, level: 1 })).toBeVisible();

      await call("write_info", { board_id: boardId, loop_id: loopId, content: plan.INFO });
      const info = await openDocument(page, "Info");
      await expect(info.getByLabel("Write or revise Info")).toHaveValue(plan.INFO);
      await closeDialog(page);
    });

    await test.step("write_analysis with a brief; the person reads both views and approves", async () => {
      const written = await call("write_analysis", {
        board_id: boardId,
        loop_id: loopId,
        analysis: plan.ANALYSIS,
        brief: plan.ANALYSIS_BRIEF,
      });
      expect(written.brief).toMatchObject({ written: true, through: "mcp" });
      const analysis = await openDocument(page, "Analysis");
      await expect(
        analysis.getByRole("button", { name: "For people", exact: true }),
      ).toHaveAttribute("aria-pressed", "true");
      await expect(analysis.getByText(plan.ANALYSIS_SUMMARY)).toBeVisible();
      await expect(analysis.getByText(plan.OBSTACLE)).toBeVisible();
      await analysis.getByRole("button", { name: "For AI", exact: true }).click();
      await expect(analysis.getByText(plan.TECHNICAL_DETAIL)).toBeVisible();
      await analysis.getByRole("button", { name: "Approve analysis" }).click();
      await expect(analysis.getByRole("button", { name: "Approved" })).toBeVisible();
      await closeDialog(page);
    });

    await test.step("write_roadmap; the person approves; the Kanban shows the Tickets", async () => {
      const written = await call("write_roadmap", {
        board_id: boardId,
        loop_id: loopId,
        plan: plan.ROADMAP,
        brief: plan.ROADMAP_BRIEF,
      });
      Object.assign(ids, (written.id_map as { tickets: Record<string, string> }).tickets);
      const roadmap = await openDocument(page, "RoadMap");
      await expect(roadmap.getByText(plan.ORDER_STEP)).toBeVisible();
      await roadmap.getByRole("button", { name: "Approve RoadMap" }).click();
      await expect(roadmap.getByRole("button", { name: "Approved" })).toBeVisible();
      await closeDialog(page);

      await page.reload();
      const keyed = new RegExp(`${loopKey}-[A-Z0-9]{2}\\d{2,}-\\d{3}`);
      for (const title of [plan.READY, plan.AFTER, plan.WAITING]) {
        await expect(tile(page, title)).toContainText(keyed);
      }
      await expect(tile(page, plan.READY)).toContainText("Development");
      await expect(tile(page, plan.READY).getByText(/^(Blocked|Needs input)$/)).toHaveCount(0);
      await expect(tile(page, plan.AFTER).getByText("Blocked", { exact: true })).toBeVisible();
      await expect(
        tile(page, plan.WAITING).getByText("Needs input", { exact: true }),
      ).toBeVisible();

      const after = await openTicket(page, plan.AFTER);
      // The head names the Phase; the rail's state says what holds the Ticket up.
      await expect(after.getByText(/^Phase 2 · /)).toBeVisible();
      await expect(
        after.getByRole("region", { name: "Status" }).getByText("Blocked", { exact: true }),
      ).toBeVisible();
      // For you shows the face the worker wrote: the steps, nothing of the agent's own text.
      await expect(after.getByRole("list", { name: "Steps" })).toBeVisible();
      await closeDialog(page);
      const ready = await openTicket(page, plan.READY);
      await expect(ready.getByText(/^Phase 1 · /)).toBeVisible();
      await expect(ready.getByText("Ready", { exact: true })).toBeVisible();
      await closeDialog(page);
    });

    await test.step("list_tickets names the ready Ticket; read_ticket says what it may do", async () => {
      const listed = await call("list_tickets", {
        board_id: boardId,
        loop_id: loopId,
        state: ["ready"],
      });
      const rows = rowsOf<{ id: string; title: string }>(listed, "tickets");
      expect(rows.map((row) => row.title)).toEqual([plan.READY]);
      expect(rows[0]?.id).toBe(ids.t1);

      const read = await call("read_ticket", { board_id: boardId, card_id: ids.t1 });
      expect(read.allowed_actions).toEqual(
        expect.arrayContaining(["complete_ticket", "set_ticket_wait"]),
      );
      expect(read.ticket).toMatchObject({
        workplace: "codebase",
        labels: ["Development"],
        plan: { phase: { number: 1, name: "Idle check" } },
      });
    });

    await test.step("set_ticket_wait; the person sees the question and clears the wait", async () => {
      await call("set_ticket_wait", {
        board_id: boardId,
        card_id: ids.t1,
        waiting_for: "decision",
        reason: plan.WAIT_REASON,
      });
      const dialog = await openTicket(page, plan.READY);
      await expect(dialog.getByText("Needs input", { exact: true })).toBeVisible();
      await expect(dialog.getByText(plan.WAIT_REASON)).toBeVisible();
      await dialog.getByRole("button", { name: "Clear the wait" }).click();
      await expect(dialog.getByText("Ready", { exact: true })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Clear the wait" })).toHaveCount(0);
      await closeDialog(page);
    });

    await test.step("comment_ticket and complete_ticket show in the dialog and on the Kanban", async () => {
      await call("comment_ticket", { board_id: boardId, card_id: ids.t1, content: plan.COMMENT });
      const dialog = await openTicket(page, plan.READY);
      await expect(dialog.getByText(plan.COMMENT)).toBeVisible();
      await closeDialog(page);

      await call("complete_ticket", {
        board_id: boardId,
        card_id: ids.t1,
        summary: "The guard ends sessions idle for more than 30 minutes.",
        evidence: ["The unit suite passed"],
      });
      await page.reload();
      await expect(tile(page, plan.READY).getByText("done", { exact: true })).toBeVisible();
      // Its prerequisite is done, so the Ticket after it is no longer held up.
      await expect(tile(page, plan.AFTER).getByText("Blocked", { exact: true })).toHaveCount(0);
    });

    await test.step("create_ticket is Unplanned; write_note is in the Notes panel", async () => {
      await call("create_ticket", {
        board_id: boardId,
        loop_id: loopId,
        title: plan.FOLLOW_UP,
        description: "Found while adding the idle check.",
        follow_up_of: ids.t1,
        workplace: "codebase",
      });
      await page.reload();
      const followUp = tile(page, plan.FOLLOW_UP);
      await expect(followUp.getByText("Unplanned", { exact: true })).toBeVisible();
      await expect(followUp).toContainText(`${loopKey}-UNP-`);

      await call("write_note", { board_id: boardId, loop_id: loopId, content: plan.NOTE });
      await page.reload();
      await page.getByRole("button", { name: "Notes", exact: true }).click();
      const notes = page.getByRole("dialog", { name: `${loopKey} notes` });
      await expect(notes.getByRole("list", { name: "Notes" })).toContainText(plan.NOTE);
      await closeDialog(page);
    });

    await test.step("a file the person attaches is read through read_attachment", async () => {
      const before = await call("list_attachments", { board_id: boardId, card_id: ids.t2 });
      expect(rowsOf(before, "attachments")).toEqual([]);

      const dialog = await openTicket(page, plan.AFTER);
      await expect(dialog.getByText("No files yet")).toBeVisible();
      await expect(
        dialog.getByRole("button", { name: /^Drop a file here, or use Add file\./ }),
      ).toBeVisible();
      await dialog.getByLabel("Choose files to attach").setInputFiles({
        name: plan.FILE_NAME,
        mimeType: "text/plain",
        buffer: Buffer.from(plan.FILE_TEXT, "utf8"),
      });
      await expect(dialog.getByRole("list", { name: "Uploads" })).toContainText("Uploaded");
      await expect(dialog.getByRole("list", { name: "Attached files" })).toContainText(
        plan.FILE_NAME,
      );
      await expect(dialog.getByRole("link", { name: `Download ${plan.FILE_NAME}` })).toBeVisible();
      await closeDialog(page);

      const after = await call("list_attachments", { board_id: boardId, card_id: ids.t2 });
      const files = rowsOf<{ id: string; filename: string; text: boolean }>(after, "attachments");
      expect(files).toHaveLength(1);
      expect(files[0]).toMatchObject({ filename: plan.FILE_NAME, text: true });
      const read = await call("read_attachment", {
        board_id: boardId,
        attachment_id: files[0]?.id,
      });
      expect(String(read.text)).toContain("median 12 minutes");
    });

    await test.step("axe finds nothing serious on the Loop page and its new sections", async () => {
      await page.reload();
      await expect(tile(page, plan.FOLLOW_UP)).toBeVisible();
      expect(await blockingViolations(page, testInfo, "axe-loop-kanban")).toEqual([]);
      await openTicket(page, plan.AFTER);
      expect(await blockingViolations(page, testInfo, "axe-ticket-dialog")).toEqual([]);
      await closeDialog(page);
      const analysis = await openDocument(page, "Analysis");
      await expect(analysis.getByText(plan.ANALYSIS_SUMMARY)).toBeVisible();
      expect(await blockingViolations(page, testInfo, "axe-analysis-brief")).toEqual([]);
      await closeDialog(page);
      const roadmap = await openDocument(page, "RoadMap");
      await expect(roadmap.getByText(plan.ORDER_STEP)).toBeVisible();
      expect(await blockingViolations(page, testInfo, "axe-roadmap-brief")).toEqual([]);
      await closeDialog(page);
      await page.getByRole("button", { name: "Notes", exact: true }).click();
      await expect(page.getByRole("list", { name: "Notes" })).toContainText(plan.NOTE);
      expect(await blockingViolations(page, testInfo, "axe-notes")).toEqual([]);
      await closeDialog(page);
    });
  });
});
