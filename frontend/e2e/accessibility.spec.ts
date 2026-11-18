import { expect, test, type Page } from "playwright/test";
import { blockingViolations } from "./axe";
import { activityTab, askOnly, CLOSED_ENDPOINT, createAgent } from "./discussion";
import {
  addCard,
  boardWithLoop,
  closeDialog,
  createBoard,
  createLoop,
  login,
  openBoardFromDashboard,
  openCard,
  openPlanDocument,
  showTab,
  uniqueName,
} from "./support";

type Kit = "Classic" | "CareNomad" | "MatchMap";
type Mode = "Dark" | "Light";

/** Every kit in both modes. In Classic color-contrast blocks; elsewhere it is an annotation. */
const THEMES: readonly (readonly [Kit, Mode])[] = [
  ["Classic", "Dark"],
  ["Classic", "Light"],
  ["CareNomad", "Dark"],
  ["CareNomad", "Light"],
  ["MatchMap", "Dark"],
  ["MatchMap", "Light"],
];

/** This browser's stored choice, which the signed-out pages show (themes/theme.ts). */
async function storeAppearance(page: Page, kit: Kit, mode: Mode): Promise<void> {
  await page.evaluate(
    ([storedKit, storedMode]) => {
      localStorage.setItem("tralala-theme-kit", storedKit);
      localStorage.setItem("tralala-theme", storedMode);
    },
    [kit.toLowerCase(), mode.toLowerCase()] as const,
  );
  await page.reload();
  await expectAppearance(page, kit, mode);
}

/** The account's choice, made as a person makes it: Settings, Appearance. */
async function chooseAppearance(page: Page, kit: Kit, mode: Mode): Promise<void> {
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
  await page
    .getByRole("radiogroup", { name: "Theme kit" })
    .getByRole("radio", { name: new RegExp(`^${kit}`) })
    .click();
  await page
    .getByRole("radiogroup", { name: "Theme mode" })
    .getByRole("radio", { name: new RegExp(`^${mode}`) })
    .click();
  await expectAppearance(page, kit, mode);
}

async function expectAppearance(page: Page, kit: Kit, mode: Mode): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-theme-kit", kit.toLowerCase());
  await expect(page.locator("html")).toHaveAttribute("data-theme", mode.toLowerCase());
}

test.describe("accessibility", () => {
  test("the dashboard has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    const name = uniqueName("Accessible board");
    await createBoard(page, name);
    await page.getByRole("link", { name: "Boards" }).click();
    await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: /^Waits for you/, level: 2 })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });

  test("a board page has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    const name = uniqueName("Accessible board");
    await boardWithLoop(page, name);
    await openBoardFromDashboard(page, name);
    await expect(page.getByRole("list", { name: "Current Loops" })).toBeVisible();
    await page.getByText("Agents and repositories").click();
    await page.getByRole("button", { name: "Board actions" }).click();
    await expect(page.getByRole("menu", { name: "Board actions" })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });

  test("a Loop page has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Accessible board"));
    await addCard(page, "Todo", "An accessible card");
    await page.getByRole("button", { name: "Loop actions" }).click();
    await expect(page.getByRole("menu", { name: "Loop actions" })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
    await page.keyboard.press("Escape");
    await openPlanDocument(page, "Info");
    expect(await blockingViolations(page, testInfo, "axe-loop-plan")).toEqual([]);
    await showTab(page, "Notes");
    expect(await blockingViolations(page, testInfo, "axe-loop-notes")).toEqual([]);
  });

  test("a Ticket over the Kanban has no serious or critical axe violations", async ({
    page,
  }, testInfo) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Accessible board"));
    await addCard(page, "Todo", "An accessible Ticket");
    const dialog = await openCard(page, "Todo", "An accessible Ticket");
    await expect(dialog.getByRole("heading", { name: "An accessible Ticket" })).toBeVisible();
    await expect(dialog.getByLabel("Add a note", { exact: true })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
    await dialog.getByRole("tab", { name: "Raw text" }).click();
    expect(await blockingViolations(page, testInfo, "axe-ticket-raw")).toEqual([]);
  });

  test("a discussion over the Kanban and the inbox have no serious or critical axe violations", async ({
    page,
  }, testInfo) => {
    await login(page);
    const { boardId, loopId } = await boardWithLoop(page, uniqueName("Accessible board"));
    await addCard(page, "Todo", "An accessible question");
    const agentName = uniqueName("Accessible Agent");
    await createAgent(page, agentName, CLOSED_ENDPOINT);
    await page.goto(`/boards/${boardId}/loops/${loopId}`);
    const ticket = await openCard(page, "Todo", "An accessible question");
    await activityTab(ticket, /^Discussions/);
    await ticket.getByRole("button", { name: "Ask the agents" }).first().click();
    const question = `Is this readable? ${uniqueName("Q")}`;
    await askOnly(page, agentName, question);
    const thread = page.getByRole("dialog", { name: question });
    await expect(
      thread.getByText(`No answer from ${agentName}: the agent could not be reached.`),
    ).toBeVisible({ timeout: 30_000 });

    expect(await blockingViolations(page, testInfo, "axe-discussion-modal")).toEqual([]);
    await page.goto("/discussions");
    await expect(
      page.getByRole("list", { name: "Waits for your decision" }).getByText(question),
    ).toBeVisible();
    expect(await blockingViolations(page, testInfo, "axe-discussion-inbox")).toEqual([]);
  });

  test("the first Tab reaches the skip link, and a new page takes focus on its heading", async ({
    page,
  }) => {
    await login(page);
    // A fresh load: focus starts at the top of the document, not where the login left it.
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
    await expect(page).toHaveTitle("Boards · Tralala");

    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main")).toBeFocused();

    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeFocused();
    await expect(page).toHaveTitle("Settings · Tralala");
  });

  test("Settings has no serious or critical axe violations", async ({ page }, testInfo) => {
    await login(page);
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Change password" })).toBeVisible();

    expect(await blockingViolations(page, testInfo)).toEqual([]);
  });
});

test.describe("accessibility in each theme", () => {
  // The appearance belongs to the shared administrator account. Put it back on the default even when
  // a check fails, so the specs after this one start from CareNomad, dark, as they expect.
  test.afterEach(async ({ page }) => {
    const cookies = await page.context().cookies();
    const csrf = cookies.find((cookie) => cookie.name === "tralala_csrf");
    if (!csrf) return;
    await page.request.put("/api/v1/auth/preferences", {
      headers: { "X-CSRF-Token": csrf.value },
      data: { theme_mode: "dark", theme_kit: "carenomad" },
    });
  });

  for (const [kit, mode] of THEMES) {
    test(`${kit} ${mode.toLowerCase()}: sign-in, dashboard, dialogs, a Loop and a Ticket pass axe`, async ({
      page,
    }, testInfo) => {
      test.setTimeout(120_000);
      const prefix = `axe-${kit.toLowerCase()}-${mode.toLowerCase()}`;
      // Soft, so one run lists every state that fails in this theme, not just the first.
      await page.goto("/login");
      await storeAppearance(page, kit, mode);
      await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
      expect.soft(await blockingViolations(page, testInfo, `${prefix}-login`)).toEqual([]);

      await login(page);
      await chooseAppearance(page, kit, mode);

      await page.getByRole("link", { name: "Boards" }).click();
      await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
      await page.getByRole("button", { name: "New board" }).click();
      const newBoard = page.getByRole("dialog", { name: "New board" });
      await expect(newBoard.getByLabel("Name")).toBeVisible();
      expect.soft(await blockingViolations(page, testInfo, `${prefix}-new-board`)).toEqual([]);
      const boardName = uniqueName(`${kit} ${mode} board`);
      await newBoard.getByLabel("Name").fill(boardName);
      await newBoard.getByRole("button", { name: "Create board" }).click();
      await expect(page.getByRole("heading", { name: boardName, level: 1 })).toBeVisible();

      await createLoop(page, "Delivery");
      await addCard(page, "Todo", "A themed Ticket");
      expect.soft(await blockingViolations(page, testInfo, `${prefix}-loop`)).toEqual([]);
      const ticket = await openCard(page, "Todo", "A themed Ticket");
      await expect(ticket.getByRole("heading", { name: "A themed Ticket" })).toBeVisible();
      expect.soft(await blockingViolations(page, testInfo, `${prefix}-ticket`)).toEqual([]);
      await closeDialog(page);

      await page.getByRole("link", { name: "Boards" }).click();
      await expect(page.getByRole("button", { name: boardName, exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: /^Waits for you/, level: 2 })).toBeVisible();
      expect.soft(await blockingViolations(page, testInfo, `${prefix}-dashboard`)).toEqual([]);

      await page.getByRole("link", { name: "Settings" }).click();
      await page.getByRole("button", { name: "New access key" }).click();
      const access = page.getByRole("dialog", { name: "New interaction agent access" });
      await access.getByLabel("Agent name").fill(uniqueName(`${kit} ${mode} agent`));
      // The scope list arrives with /meta; wait for it so the dialog is complete when it is sent.
      await expect(access.getByLabel("boards:read")).toBeVisible();
      await access.getByRole("button", { name: "Create access" }).click();
      const issued = page.getByRole("dialog", { name: "Copy this token now" });
      await expect(issued.getByLabel("New API token")).toBeVisible();
      expect.soft(await blockingViolations(page, testInfo, `${prefix}-issued-token`)).toEqual([]);
      await issued.getByRole("button", { name: "Done" }).click();
    });
  }
});
