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

    const dialog = await openCard(page, "Todo", cardTitle);
    // The title is the dialog's heading; a click edits it and Enter saves it.
    await dialog.getByRole("button", { name: cardTitle, exact: true }).click();
    const title = dialog.getByRole("textbox", { name: "Title" });
    await title.fill(`${cardTitle} (final)`);
    await title.press("Enter");
    await expect(dialog.getByRole("heading", { name: `${cardTitle} (final)` })).toBeVisible();
    await dialog
      .getByLabel("Card description (Markdown)")
      .fill(
        "## Launch plan\n\n- **Publish** release notes\n- `pnpm publish`\n\nSee https://example.com.",
      );
    await dialog.getByRole("button", { name: "Save description" }).click();
    await expect(dialog.getByRole("button", { name: "Save description" })).toBeDisabled();
    // A fact in the rail turns into its control when clicked and saves itself.
    await dialog.getByRole("button", { name: "Priority: None" }).click();
    await dialog.getByRole("option", { name: "High" }).click();
    await expect(dialog.getByRole("button", { name: "Priority: High" })).toBeVisible();
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

    await closeDialog(page);
    await expect(cardTile(page, "Todo", `${cardTitle} (final)`)).toContainText("high");
  });

  test("filters the board with server-side search", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Filter board"));
    await addCard(page, "Todo", "Fix login bug");
    await addCard(page, "Todo", "Write documentation");

    await page.getByLabel("Filter tickets").fill("login");
    await expect(cardTile(page, "Todo", "Fix login bug")).toBeVisible();
    await expect(cardTile(page, "Todo", "Write documentation")).toHaveCount(0);

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
  });
});
