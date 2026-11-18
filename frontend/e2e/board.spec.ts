import { expect, test } from "playwright/test";
import {
  addCard,
  boardWithLoop,
  cardTile,
  closeDialog,
  listRegion,
  login,
  openCard,
  uniqueName,
} from "./support";

test.describe("boards and cards", () => {
  test("creates a Loop with the default columns and edits a ticket", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Launch board"));

    for (const listName of ["Backlog", "Todo", "In Progress", "Review", "Done"]) {
      await expect(listRegion(page, listName)).toBeVisible();
    }

    const cardTitle = uniqueName("Write checklist");
    await addCard(page, "Todo", cardTitle);
    // The form closed; the focus is back on the button that opens it.
    await expect(listRegion(page, "Todo").getByRole("button", { name: "Add card" })).toBeFocused();

    const dialog = await openCard(page, "Todo", cardTitle);
    // The title is the dialog's heading; a click edits it and Enter saves it.
    await dialog.getByRole("button", { name: cardTitle, exact: true }).click();
    const title = dialog.getByRole("textbox", { name: "Title" });
    await title.fill(`${cardTitle} (final)`);
    await title.press("Enter");
    await expect(dialog.getByRole("heading", { name: `${cardTitle} (final)` })).toBeVisible();
    // The description's source is the agent's text: it is edited under Raw text.
    await dialog.getByRole("tab", { name: "Raw text" }).click();
    await dialog.getByRole("button", { name: "Edit description" }).click();
    await dialog
      .getByLabel("Card description (Markdown)")
      .fill(
        "## Launch plan\n\n- **Publish** release notes\n- `pnpm publish`\n\nSee https://example.com.",
      );
    await dialog.getByRole("tab", { name: "Preview" }).click();
    const preview = dialog.getByRole("tabpanel", { name: "Preview" });
    await expect(preview.getByRole("heading", { name: "Launch plan" })).toBeVisible();
    await expect(preview.getByRole("link", { name: "https://example.com" })).toHaveAttribute(
      "target",
      "_blank",
    );
    await dialog.getByText("How to format").click();
    await expect(
      dialog.getByText("Links to other sites open in a new tab; only http(s) links become links."),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Save description" }).click();
    await expect(dialog.getByRole("button", { name: "Save description" })).toHaveCount(0);
    await expect(dialog.getByRole("tabpanel", { name: "Raw text" })).toContainText(
      "## Launch plan",
    );
    // A Ticket without a face reads by its description under For you.
    await dialog.getByRole("tab", { name: "For you" }).click();
    const forYou = dialog.getByRole("tabpanel", { name: "For you" });
    await expect(forYou.getByRole("heading", { name: "Launch plan" })).toBeVisible();
    await expect(forYou).toContainText("Written before Tickets had a plain summary.");
    // A fact in the rail turns into its control when clicked and saves itself.
    await dialog.getByRole("button", { name: "Priority: None" }).click();
    await dialog.getByRole("option", { name: "High" }).click();
    await expect(dialog.getByRole("button", { name: "Priority: High" })).toBeVisible();

    await closeDialog(page);
    await expect(cardTile(page, "Todo", `${cardTitle} (final)`)).toContainText("High");
  });

  test("filters the board with server-side search", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Filter board"));
    await addCard(page, "Todo", "Fix login bug");
    await addCard(page, "Todo", "Write documentation");

    await page.getByLabel("Filter tickets").fill("login");
    await expect(cardTile(page, "Todo", "Fix login bug")).toBeVisible();
    await expect(cardTile(page, "Todo", "Write documentation")).toHaveCount(0);
    // The count is on screen and in the announcer; an empty column says why it is empty.
    await expect(page.getByText("1 Ticket matches", { exact: true })).toBeVisible();
    await expect(page.locator('[data-announcer="polite"]')).toContainText("1 Ticket matches");
    await expect(listRegion(page, "Review")).toContainText("No Tickets match the filter");

    await page.getByLabel("Filter tickets").fill("");
    await expect(cardTile(page, "Todo", "Write documentation")).toBeVisible();
  });

  test("archives a card and hides it from the board", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Archive board"));
    await addCard(page, "Backlog", "Temporary card");

    const dialog = await openCard(page, "Backlog", "Temporary card");
    await dialog.getByRole("button", { name: "More actions" }).click();
    await dialog
      .getByRole("list", { name: "More actions" })
      .getByRole("button", { name: "Archive" })
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(cardTile(page, "Backlog", "Temporary card")).toHaveCount(0);
    // The card left the board, so the focus is on its column's Add card; Undo brings it back.
    await expect(
      listRegion(page, "Backlog").getByRole("button", { name: "Add card" }),
    ).toBeFocused();
    await expect(page.getByText("Ticket archived", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(page.getByText("Ticket restored", { exact: true })).toBeVisible();
    await expect(cardTile(page, "Backlog", "Temporary card")).toBeVisible();
  });

  test("keeps the Kanban usable in a window as small as 400% zoom", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Zoom board"));
    // 1280 x 1024 at 400%: 320 x 256 CSS pixels.
    await page.setViewportSize({ width: 320, height: 256 });
    const columns = page.getByRole("region", { name: "Loop Kanban columns" });
    await columns.scrollIntoViewIfNeeded();
    const box = await columns.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(200);
    // The header is not sticky here, so it never covers the focused control.
    await expect(page.locator("header").first()).not.toHaveCSS("position", "sticky");
  });

  test("shows a due date that has passed as Overdue in words", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Due board"));
    await addCard(page, "Todo", "Late task");
    const dialog = await openCard(page, "Todo", "Late task");
    await dialog.getByRole("button", { name: "Due: None" }).click();
    await dialog.getByLabel("Due date").fill("2000-01-31");
    await dialog.getByLabel("Due date").press("Enter");
    await closeDialog(page);
    await expect(cardTile(page, "Todo", "Late task")).toContainText("Overdue");
  });
});
