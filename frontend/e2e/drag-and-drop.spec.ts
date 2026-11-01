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
    const handle = done.getByRole("button", { name: "Reorder list Done" });
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

    await expect(page.getByRole("region", { name: /^List / }).first()).toHaveAccessibleName(
      "List Done",
    );
  });
});
