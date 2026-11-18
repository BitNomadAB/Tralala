import { expect, test } from "playwright/test";
import {
  addCard,
  cardTile,
  boardWithLoop,
  dragCardToList,
  listRegion,
  login,
  uniqueName,
} from "./support";

test.describe("drag and drop", () => {
  test("moves a card between lists and persists the position after reload", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Drag board"));

    const title = uniqueName("Drag me");
    await addCard(page, "Todo", title);
    await dragCardToList(page, title, "Todo", "In Progress");

    await expect(listRegion(page, "Todo").getByRole("listitem")).toHaveCount(0);
    await expect(listRegion(page, "In Progress").getByRole("listitem")).toHaveCount(1);

    await page.reload();
    await expect(cardTile(page, "In Progress", title)).toBeVisible();
    await expect(listRegion(page, "Todo").getByRole("listitem")).toHaveCount(0);
  });

  test("reorders lists horizontally", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("List order board"));

    const done = listRegion(page, "Done");
    const target = listRegion(page, "Backlog");
    const handle = done.getByRole("button", { name: "Reorder column Done" });
    const handleBox = await handle.boundingBox();
    const targetBox = await target.boundingBox();
    if (!handleBox || !targetBox) throw new Error("Reorder handles are not visible");

    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down();
    for (let step = 1; step <= 20; step += 1) {
      await page.mouse.move(
        handleBox.x + ((targetBox.x + 40 - handleBox.x) * step) / 20,
        handleBox.y,
      );
      await page.waitForTimeout(20);
    }
    await page.mouse.up();

    await expect(page.getByRole("region", { name: /^Column / }).first()).toHaveAccessibleName(
      "Column Done",
    );
  });

  test("opens a Ticket and moves it with the keyboard alone", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Keyboard board"));
    const title = uniqueName("Keyboard card");
    await addCard(page, "Todo", title);

    // Tab from the column's menu reaches the card's title; Enter opens the Ticket.
    const todo = listRegion(page, "Todo");
    await todo.getByRole("button", { name: "Column actions for Todo" }).focus();
    await page.keyboard.press("Tab");
    const open = cardTile(page, "Todo", title).getByRole("button", { name: title, exact: true });
    await expect(open).toBeFocused();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: title });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(open).toBeFocused();

    // The next Tab is the card's grip: Space picks it up, ArrowRight carries it to the next
    // column, Space drops it there.
    await page.keyboard.press("Tab");
    const grip = cardTile(page, "Todo", title).getByRole("button", {
      name: `Move ${title}`,
      exact: true,
    });
    await expect(grip).toBeFocused();
    // dnd-kit reads every step in its own live region, by the Ticket's title and column.
    const said = page.locator('[id^="DndLiveRegion"]');
    await page.keyboard.press("Space");
    await expect(grip).toHaveAttribute("aria-pressed", "true");
    await expect(said).toContainText(title);
    await page.keyboard.press("ArrowRight");
    await expect(said).toContainText(`${title} is over In Progress`);
    await page.keyboard.press("Space");
    await expect(said).toContainText(`${title} dropped in In Progress, position 1 of 1.`);
    await expect(cardTile(page, "In Progress", title)).toBeVisible();
    await expect(todo.getByRole("listitem")).toHaveCount(0);
    // The card is rendered anew in its new column; its grip there keeps the focus.
    await expect(
      cardTile(page, "In Progress", title).getByRole("button", {
        name: `Move ${title}`,
        exact: true,
      }),
    ).toBeFocused();

    await page.reload();
    await expect(cardTile(page, "In Progress", title)).toBeVisible();
  });

  test("moves a card and a column from their menus, without dragging", async ({ page }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Menu move board"));
    const title = uniqueName("Menu card");
    await addCard(page, "Todo", title);

    await cardTile(page, "Todo", title)
      .getByRole("button", { name: `Actions for ${title}`, exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Move to Done" }).click();
    const moved = cardTile(page, "Done", title);
    await expect(moved).toBeVisible();
    await expect(moved.getByRole("button", { name: `Actions for ${title}` })).toBeFocused();
    await expect(page.locator('[data-announcer="polite"]')).toContainText(
      `${title} moved to Done, position 1 of 1.`,
    );

    await listRegion(page, "Backlog")
      .getByRole("button", { name: "Column actions for Backlog" })
      .click();
    await expect(
      page.getByRole("menuitem", { name: "Move left: Already the first column" }),
    ).toBeVisible();
    await page.getByRole("menuitem", { name: "Move right" }).click();
    await expect(page.getByRole("region", { name: /^Column / }).nth(1)).toHaveAccessibleName(
      "Column Backlog",
    );
    await expect(page.getByRole("button", { name: "Column actions for Backlog" })).toBeFocused();

    await page.reload();
    await expect(cardTile(page, "Done", title)).toBeVisible();
    await expect(page.getByRole("region", { name: /^Column / }).first()).toHaveAccessibleName(
      "Column Todo",
    );
  });
});
