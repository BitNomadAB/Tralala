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
    await page.keyboard.press("Space");
    await expect(grip).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Space");
    await expect(cardTile(page, "In Progress", title)).toBeVisible();
    await expect(todo.getByRole("listitem")).toHaveCount(0);

    await page.reload();
    await expect(cardTile(page, "In Progress", title)).toBeVisible();
  });
});
