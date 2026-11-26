import { expect, test, type Locator, type Page } from "playwright/test";
import { blockingViolations } from "./axe";
import { mcpCall, type ToolAnswer } from "./mcp";
import { boardIdFromUrl, createBoard, issueToken, login, uniqueName } from "./support";

/** What a worker key needs to find, open, answer and read the board's discussions. */
const DISCUSSION_SCOPES = ["boards:read", "discussions:read", "discussions:write"];

/** One thread named in a tool answer's `notices`. */
interface NoticeThread {
  discussion_id: string;
  board_id: string;
  title: string;
  reason: string;
}

/** The threads a tool answer's `notices` names; none when the answer carries no notices. */
function noticedThreads(answer: ToolAnswer): NoticeThread[] {
  const notices = answer.notices as { threads?: NoticeThread[] } | undefined;
  return notices?.threads ?? [];
}

/** The board page's own discussions, beside its Loops. */
function boardDiscussions(page: Page): Locator {
  return page.getByRole("region", { name: "Discussions", exact: true });
}

/** The row of the board's list under `filter` whose title is `title`. */
async function boardRow(page: Page, filter: "Open" | "Closed", title: string): Promise<Locator> {
  const section = boardDiscussions(page);
  const tab = section
    .getByRole("tablist", { name: "Show discussions" })
    .getByRole("tab", { name: filter, exact: true });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  return section
    .getByRole("list", { name: `${filter} discussions` })
    .getByRole("link")
    .filter({ hasText: title });
}

/** Writes in the open discussion's reply form and presses its button (`action`). */
async function reply(page: Page, text: string, action: "Send" | "Add comment"): Promise<void> {
  const form = page.getByRole("form", { name: "Your reply" });
  await form.getByRole("textbox", { name: "Reply" }).fill(text);
  await form.getByRole("button", { name: action, exact: true }).click();
  await expect(page.getByRole("list", { name: "Comments" }).getByText(text)).toBeVisible();
  await expect(form.getByRole("textbox", { name: "Reply" })).toHaveValue("");
}

test.describe("a discussion on the board", () => {
  test.use({ viewport: { width: 1600, height: 900 } });

  test("a person opens, answers, closes, comments after the close and reopens it; a key's answer shows as unread", async ({
    page,
  }, testInfo) => {
    test.setTimeout(120_000);
    await login(page);
    const boardName = uniqueName("Board talk");
    await createBoard(page, boardName);
    const boardId = boardIdFromUrl(page);
    const boardPath = `/boards/${boardId}`;
    const title = uniqueName("Release window");
    const question = "Which week suits the release best?";
    const status = page.getByRole("group", { name: "Status" });
    let discussionId = "";

    await test.step("New discussion with a title, a question and no agents opens it", async () => {
      await expect(page.getByRole("heading", { name: "Discussions", level: 2 })).toBeVisible();
      await boardDiscussions(page).getByRole("button", { name: "New discussion" }).click();
      const dialog = page.getByRole("dialog", { name: "New discussion" });
      await dialog.getByRole("textbox", { name: "Title" }).fill(title);
      await dialog.getByRole("textbox", { name: "Question" }).fill(question);
      // Agents other journeys left on the stack are offered, none of them chosen.
      const agents = dialog.getByRole("group", { name: "Agents (optional)" });
      for (const agent of await agents.getByRole("checkbox").all()) {
        await expect(agent).not.toBeChecked();
      }
      expect(await blockingViolations(page, testInfo, "axe-new-discussion")).toEqual([]);
      await dialog.getByRole("button", { name: "Start discussion" }).click();
      await expect(dialog).toHaveCount(0);
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`${boardPath}/discussions/[0-9a-f-]{36}$`));
      discussionId = new URL(page.url()).pathname.split("/").pop() ?? "";
      expect(await blockingViolations(page, testInfo, "axe-board-discussion")).toEqual([]);
    });

    await test.step("the board lists it under Open", async () => {
      await page.getByRole("button", { name: "Back to the board" }).click();
      await expect(page.getByRole("heading", { name: boardName, level: 1 })).toBeVisible();
      const open = boardDiscussions(page).getByRole("tab", { name: "Open", exact: true });
      await expect(open).toHaveAttribute("aria-selected", "true");
      const row = await boardRow(page, "Open", title);
      await expect(row).toBeVisible();
      await expect(row).not.toHaveText(/^Unread\b/);
      await row.click();
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    });

    await test.step("the person replies in it", async () => {
      await reply(page, "The second week of March, after the freeze.", "Send");
    });

    await test.step("Close discussion asks first, then the thread is Closed", async () => {
      await page.getByRole("button", { name: "Close discussion", exact: true }).click();
      const confirm = page.getByRole("dialog", { name: "Close this discussion?" });
      await confirm.getByRole("button", { name: "Close discussion", exact: true }).click();
      await expect(confirm).toHaveCount(0);
      await expect(status).toContainText("Closed");
      await expect(page.getByRole("button", { name: "Reopen", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Close discussion" })).toHaveCount(0);

      await page.getByRole("button", { name: "Back to the board" }).click();
      await expect(await boardRow(page, "Open", title)).toHaveCount(0);
      const row = await boardRow(page, "Closed", title);
      await expect(row).toBeVisible();
      await row.click();
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    });

    await test.step("a comment after the close carries the mark After closing", async () => {
      const late = "Moved to April, see the freeze notes.";
      await reply(page, late, "Add comment");
      const comment = page
        .getByRole("list", { name: "Comments" })
        .getByRole("listitem")
        .filter({ hasText: late });
      await expect(comment.getByText("After closing", { exact: true })).toBeVisible();
      const early = page
        .getByRole("list", { name: "Comments" })
        .getByRole("listitem")
        .filter({ hasText: "The second week of March" });
      await expect(early.getByText("After closing", { exact: true })).toHaveCount(0);
    });

    await test.step("Reopen opens it again", async () => {
      await page.getByRole("button", { name: "Reopen", exact: true }).click();
      await expect(status).not.toContainText("Closed");
      await expect(
        page.getByRole("button", { name: "Close discussion", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("form", { name: "Your reply" }).getByRole("button", { name: "Send" }),
      ).toBeVisible();
    });

    await test.step("a key's answer marks the row Unread until the person opens it", async () => {
      // The person leaves the thread, so the open page marks nothing read while the key writes.
      // Times are kept to the second and only what is written after the person's marker is new,
      // so the key answers in a later second than the person last read the thread.
      await page.getByRole("button", { name: "Back to the board" }).click();
      await expect(boardDiscussions(page)).toBeVisible();
      await page.waitForTimeout(1_100);
      const token = await issueToken(page, DISCUSSION_SCOPES);
      const answer = await mcpCall(page, token, "reply_discussion", {
        board_id: boardId,
        discussion_id: discussionId,
        content: "April works for the integration tests too.",
      });
      expect(answer.discussion_id).toBe(discussionId);

      await page.goto(boardPath);
      const row = await boardRow(page, "Open", title);
      await expect(row).toHaveText(/^Unread\b/);
      await row.click();
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
      await expect(
        page.getByRole("list", { name: "Comments" }).getByText("April works for the integration"),
      ).toBeVisible();
      await page.getByRole("button", { name: "Back to the board" }).click();
      await expect(await boardRow(page, "Open", title)).not.toHaveText(/^Unread\b/);
    });
  });

  // FIXME product defect: `/mcp` tools/call runs the tool's handler directly
  // (backend/app/api/mcp.py), so `with_notices` (reached only through `run_tool`, which nothing
  // calls) never adds `notices` to an answer. The step "the key's next tool call carries the
  // thread in notices" fails with no notices at all, although the thread waits for the key.
  test.fixme("a key that opened a discussion finds the person's answer in notices until it reads it", async ({
    page,
  }) => {
    await login(page);
    await createBoard(page, uniqueName("Board notices"));
    const boardId = boardIdFromUrl(page);
    const token = await issueToken(page, DISCUSSION_SCOPES);
    const call = (name: string, args: Record<string, unknown>) =>
      mcpCall(page, token, name, { board_id: boardId, ...args });
    const title = uniqueName("Index rebuild");
    let discussionId = "";

    await test.step("the key opens a discussion on the board; nothing waits for it yet", async () => {
      const opened = await call("open_discussion", {
        title,
        question: "Should the search index be rebuilt nightly?",
      });
      expect(typeof opened.discussion_id).toBe("string");
      discussionId = String(opened.discussion_id);
      const listed = await call("list_discussions", {});
      expect(noticedThreads(listed).map((entry) => entry.discussion_id)).not.toContain(
        discussionId,
      );
    });

    await test.step("the person answers it in the browser", async () => {
      await page.goto(`/boards/${boardId}`);
      const row = await boardRow(page, "Open", title);
      await row.click();
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
      await expect(page.getByRole("button", { name: "Close discussion" })).toHaveCount(0);
      await reply(page, "Nightly is fine while the board is small.", "Send");
    });

    await test.step("the key's next tool call carries the thread in notices", async () => {
      const listed = await call("list_discussions", {});
      const waiting = noticedThreads(listed).filter(
        (entry) => entry.discussion_id === discussionId,
      );
      expect(waiting, JSON.stringify(listed.notices)).toEqual([
        { discussion_id: discussionId, board_id: boardId, title, reason: "answer" },
      ]);
    });

    await test.step("after read_discussion the thread leaves the notices", async () => {
      const read = await call("read_discussion", { discussion_id: discussionId });
      expect(read.discussion_id).toBe(discussionId);
      const listed = await call("list_discussions", {});
      expect(noticedThreads(listed).map((entry) => entry.discussion_id)).not.toContain(
        discussionId,
      );
    });
  });
});
