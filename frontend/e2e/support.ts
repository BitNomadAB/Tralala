import { expect, type Locator, type Page } from "playwright/test";

export const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-password",
};

export function uniqueName(prefix: string): string {
  return `${prefix} ${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

export async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username").fill(ADMIN.username);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
}

export async function createBoard(page: Page, name: string): Promise<void> {
  await page.getByRole("button", { name: "New board" }).click();
  const dialog = page.getByRole("dialog", { name: "New board" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("button", { name: "Create board" }).click();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
  await expect(listRegion(page, "Todo")).toBeVisible();
}

export function listRegion(page: Page, listName: string): Locator {
  return page.getByRole("region", { name: `List ${listName}` });
}

export function cardTile(page: Page, listName: string, title: string): Locator {
  return listRegion(page, listName).getByRole("listitem").filter({ hasText: title });
}

export async function addCard(page: Page, listName: string, title: string): Promise<void> {
  const list = listRegion(page, listName);
  await list.getByRole("button", { name: "Add card" }).click();
  await list.getByLabel(`New card in ${listName}`).fill(title);
  await list.getByRole("button", { name: "Add card" }).click();
  await expect(cardTile(page, listName, title)).toBeVisible();
}

export async function openCard(page: Page, listName: string, title: string): Promise<Locator> {
  await listRegion(page, listName).getByRole("button", { name: title }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

export async function closeDialog(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Close dialog" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

/** dnd-kit needs a real pointer gesture; drop onto the list body, not the header. */
export async function dragCardToList(
  page: Page,
  cardTitle: string,
  fromList: string,
  toList: string,
): Promise<void> {
  const card = cardTile(page, fromList, cardTitle);
  const targetBody = listRegion(page, toList).locator("> div").nth(1);
  const cardBox = await card.boundingBox();
  const targetBox = await targetBody.boundingBox();
  if (!cardBox || !targetBox) throw new Error("Drag source or target is not visible");

  const startX = cardBox.x + 24;
  const startY = cardBox.y + 16;
  const endX = targetBox.x + targetBox.width / 2;
  const endY = targetBox.y + Math.min(targetBox.height / 2, 80);

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  for (let step = 1; step <= 20; step += 1) {
    await page.mouse.move(
      startX + ((endX - startX) * step) / 20,
      startY + ((endY - startY) * step) / 20,
    );
    await page.waitForTimeout(20);
  }
  await page.waitForTimeout(150);
  await page.mouse.up();
  await expect(cardTile(page, toList, cardTitle)).toBeVisible();
}

export async function openBoardFromDashboard(page: Page, name: string): Promise<void> {
  await page.getByRole("link", { name: "Boards" }).click();
  await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
  await page.getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
}

export function boardIdFromUrl(page: Page): string {
  const match = /\/boards\/([0-9a-f-]{36})/.exec(page.url());
  if (!match) throw new Error(`No board id in ${page.url()}`);
  return match[1];
}

export async function csrfToken(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  const cookie = cookies.find((entry) => entry.name === "tralala_csrf");
  if (!cookie) throw new Error("CSRF cookie missing");
  return cookie.value;
}
