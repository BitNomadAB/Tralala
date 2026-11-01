import { expect, test, type Page } from "playwright/test";
import { boardWithLoop, createBoard, createLoop, listRegion, login, uniqueName } from "./support";

function templateRow(page: Page, name: string) {
  return page.getByRole("listitem").filter({ hasText: name });
}

async function openSettings(page: Page) {
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Board templates", level: 2 })).toBeVisible();
}

async function createTemplate(
  page: Page,
  name: string,
  lists: string[],
  description: string,
): Promise<void> {
  await page.getByRole("button", { name: "New template" }).click();
  await expect(page.getByRole("heading", { name: "New board template", level: 1 })).toBeVisible();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Description").fill(description);
  for (const [index, listName] of lists.entries()) {
    if (index > 0) await page.getByRole("button", { name: "Add list" }).click();
    await page.getByLabel(`List ${index + 1}`, { exact: true }).fill(listName);
  }
  await page.getByRole("button", { name: "Save template" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await expect(templateRow(page, name)).toBeVisible();
}

test.describe("board templates", () => {
  test("lists templates with edit and delete actions and starts a board from one", async ({
    page,
  }) => {
    await login(page);
    await openSettings(page);

    const templateName = uniqueName("Template");
    await createTemplate(page, templateName, ["Ideas", "Doing", "Done"], "Two week delivery board");

    const row = templateRow(page, templateName);
    await expect(row).toContainText("Ideas · Doing · Done");
    await expect(row).toContainText("Two week delivery board");

    await row.getByRole("button", { name: `Edit ${templateName}` }).click();
    await expect(page.getByRole("heading", { name: `Edit ${templateName}`, level: 1 })).toBeVisible();
    await expect(page.getByLabel("List 1", { exact: true })).toHaveValue("Ideas");
    await expect(page.getByLabel("List 3", { exact: true })).toHaveValue("Done");
    await page.getByLabel("List 2", { exact: true }).fill("Building");
    await page.getByRole("button", { name: "Add label" }).click();
    await page.getByLabel("Label 1 name", { exact: true }).fill("bug");
    await page.getByLabel("Description").fill("Updated flow");
    await page.getByRole("button", { name: "Save template" }).click();
    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
    await expect(templateRow(page, templateName)).toContainText("Ideas · Building · Done");
    await expect(templateRow(page, templateName)).toContainText("1 label");
    await expect(templateRow(page, templateName)).toContainText("Updated flow");

    await page.getByRole("link", { name: "Boards" }).click();
    const boardName = uniqueName("From template");
    await page.getByRole("button", { name: "New board" }).click();
    const dialog = page.getByRole("dialog", { name: "New board" });
    await dialog.getByLabel("Name").fill(boardName);
    await dialog.getByLabel("Start from").selectOption({ label: templateName });
    await expect(dialog.getByLabel("Description")).toHaveValue("Updated flow");
    await expect(dialog.getByText("Lists: Ideas → Building → Done")).toBeVisible();
    await dialog.getByRole("button", { name: "Create board" }).click();

    await expect(page.getByRole("heading", { name: boardName, level: 1 })).toBeVisible();
    await expect(page.getByText("Updated flow")).toBeVisible();
    await createLoop(page, "Templated loop");
    for (const name of ["Ideas", "Building", "Done"]) {
      await expect(listRegion(page, name)).toBeVisible();
    }

    await openSettings(page);
    await templateRow(page, templateName)
      .getByRole("button", { name: `Delete ${templateName}` })
      .click();
    const deleteDialog = page.getByRole("dialog", { name: "Delete template" });
    await deleteDialog.getByRole("button", { name: "Delete template" }).click();
    await expect(templateRow(page, templateName)).toHaveCount(0);
  });

  test("saves an existing board as a reusable template", async ({ page }) => {
    await login(page);
    const boardName = uniqueName("Snapshot");
    await boardWithLoop(page, boardName);

    await page.getByRole("button", { name: "Save columns as template" }).click();
    const dialog = page.getByRole("dialog", { name: "Save as template" });
    const templateName = uniqueName("Snapshot template");
    await dialog.getByLabel("Template name").fill(templateName);
    await dialog.getByLabel("Description").fill("Captured structure");
    await dialog.getByRole("button", { name: "Save template" }).click();
    await expect(dialog).toHaveCount(0);

    await openSettings(page);
    const row = templateRow(page, templateName);
    await expect(row).toContainText("Backlog · Todo · In Progress · Review · Done");
    await expect(row).toContainText("Captured structure");
  });

  test("blank board keeps the default lists", async ({ page }) => {
    await login(page);
    const boardName = uniqueName("Blank");
    await createBoard(page, boardName);
    await createLoop(page, "Blank loop");
    for (const name of ["Backlog", "Todo", "In Progress", "Review", "Done"]) {
      await expect(listRegion(page, name)).toBeVisible();
    }
  });
});

