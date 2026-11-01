import { expect, test } from "playwright/test";
import {
  addCard,
  cardTile,
  closeDialog,
  createBoard,
  listRegion,
  login,
  openCard,
  uniqueName,
} from "./support";

test.describe("boards and cards", () => {
  test("creates a board with the default workflow and edits a card", async ({ page }) => {
    await login(page);
    const boardName = uniqueName("Launch board");
    await createBoard(page, boardName);

    for (const listName of ["Backlog", "Todo", "In Progress", "Review", "Done"]) {
      await expect(listRegion(page, listName)).toBeVisible();
    }

    const cardTitle = uniqueName("Write checklist");
    await addCard(page, "Todo", cardTitle);

    const dialog = await openCard(page, "Todo", cardTitle);
    await dialog.getByLabel("Title", { exact: true }).fill(`${cardTitle} (final)`);
    await dialog
      .getByLabel("Card description (Markdown)")
      .fill("## Launch plan\n\n- **Publish** release notes\n- `pnpm publish`");
    await dialog.getByLabel("Priority", { exact: true }).selectOption("high");
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect(dialog.getByText(/version 2/)).toBeVisible();
    await dialog.getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByRole("heading", { name: "Launch plan" })).toBeVisible();

    await closeDialog(page);
    await expect(cardTile(page, "Todo", `${cardTitle} (final)`)).toContainText("high");
  });

  test("filters the board with server-side search", async ({ page }) => {
    await login(page);
    await createBoard(page, uniqueName("Filter board"));
    await addCard(page, "Todo", "Fix login bug");
    await addCard(page, "Todo", "Write documentation");

    await page.getByLabel("Filter cards").fill("login");
    await expect(cardTile(page, "Todo", "Fix login bug")).toBeVisible();
    await expect(cardTile(page, "Todo", "Write documentation")).toHaveCount(0);

    await page.getByLabel("Filter cards").fill("");
    await expect(cardTile(page, "Todo", "Write documentation")).toBeVisible();
  });

  test("archives a card and hides it from the board", async ({ page }) => {
    await login(page);
    await createBoard(page, uniqueName("Archive board"));
    await addCard(page, "Backlog", "Temporary card");

    const dialog = await openCard(page, "Backlog", "Temporary card");
    await dialog.getByRole("button", { name: "Archive" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(cardTile(page, "Backlog", "Temporary card")).toHaveCount(0);
  });
});
