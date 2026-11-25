import { expect, test, type Page } from "playwright/test";
import { approvedAnalysis, approveRoadmap, roadmap, ticketRow } from "./published-plan";
import { ADMIN, boardIdFromUrl, closeDialog, login, loopIdFromUrl } from "./support";

/**
 * A link to a person's decision, the address a coding session hands its person (`decision_link`):
 * it survives the sign-in whole, `?dialog=completion` opens the completion dialog, and
 * `?focus=clear-wait` puts the focus on "Clear the wait". The link only opens or focuses; the
 * person presses the button.
 */

const TICKET = "Write the mail";

async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

/** Signs in on the login page a signed-out address was sent to. */
async function signInHere(page: Page): Promise<void> {
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Username").fill(ADMIN.username);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test.describe("a link to a decision", () => {
  test.use({ viewport: { width: 1600, height: 900 } });

  test("opens the completion dialog after the sign-in and focuses Clear the wait", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await login(page);
    const { candidates, headers } = await approvedAnalysis(page, "Decision links");
    const plan = await page.request.post(candidates, { headers, data: roadmap([TICKET]) });
    expect(plan.status()).toBe(201);
    await approveRoadmap(page, TICKET);
    const loopPath = `/boards/${boardIdFromUrl(page)}/loops/${loopIdFromUrl(page)}`;
    const loop = (await (await page.request.get(`/api/v1${loopPath}`)).json()) as {
      data: { key: string };
    };
    const completion = `${loop.data.key} completion and QA`;
    let ticketPath = "";

    await test.step("the Ticket waits for a decision", async () => {
      await ticketRow(page, TICKET).getByRole("button", { name: TICKET, exact: true }).click();
      const dialog = page.getByRole("dialog", { name: TICKET });
      const rail = dialog.getByRole("complementary", { name: "Status and details" });
      await rail.getByRole("button", { name: "Mark as waiting…", exact: true }).click();
      await rail.getByLabel("Why (required)").fill("Which mail service do we use?");
      await rail.getByRole("button", { name: "Save the wait", exact: true }).click();
      await expect(rail.getByRole("button", { name: "Clear the wait", exact: true })).toBeVisible();
      ticketPath =
        (await dialog.getByRole("link", { name: "Open as page" }).getAttribute("href")) ?? "";
      expect(ticketPath).toMatch(/\/tickets\/[0-9a-f-]{36}$/);
      await closeDialog(page);
    });

    await test.step("signed out, the completion link opens its dialog once the person signs in", async () => {
      await signOut(page);
      await page.goto(`${loopPath}?dialog=completion`);
      await signInHere(page);
      const dialog = page.getByRole("dialog", { name: completion, exact: true });
      await expect(dialog).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`${loopPath}\\?dialog=completion$`));
      // The dialog asks; nothing is accepted until the person presses a button.
      await expect(dialog.getByRole("button", { name: "Accept implementation" })).toBeVisible();
    });

    await test.step("closing the dialog takes it out of the address, so a reload does not reopen it", async () => {
      await closeDialog(page);
      await expect(page).toHaveURL(new RegExp(`${loopPath}$`));
      await page.reload();
      await expect(page.getByRole("heading", { name: "Address check", level: 1 })).toBeVisible();
      await expect(page.getByRole("region", { name: /^Column / }).first()).toBeVisible();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    });

    await test.step("the wait's link focuses Clear the wait on the Ticket's page", async () => {
      await page.goto(`${ticketPath}?focus=clear-wait`);
      const clear = page.getByRole("button", { name: "Clear the wait", exact: true });
      await expect(clear).toBeFocused();
      await expect(page).toHaveURL(new RegExp(`${ticketPath}$`));
      await expect(page.getByRole("heading", { name: TICKET, level: 1 })).toBeVisible();
    });

    await test.step("signed out, the wait's link focuses it once the person signs in", async () => {
      await signOut(page);
      await page.goto(`${ticketPath}?focus=clear-wait`);
      await signInHere(page);
      await expect(page.getByRole("heading", { name: TICKET, level: 1 })).toBeVisible();
      await expect(page.getByRole("button", { name: "Clear the wait", exact: true })).toBeFocused();
      // Focused, not pressed: the Ticket still waits.
      const rail = page.getByRole("complementary", { name: "Status and details" });
      await expect(rail.getByText("Which mail service do we use?")).toBeVisible();
    });
  });
});
