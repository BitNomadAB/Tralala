import { expect, test } from "playwright/test";
import { login, uniqueName } from "./support";

test("an administrator creates a member who cannot manage accounts", async ({ page }) => {
  await login(page);
  await page.goto("/settings");
  const name = uniqueName("member").replace(/\s+/g, "-").toLowerCase();
  const password = "member-password-1";

  await page.getByRole("button", { name: "New user" }).click();
  const dialog = page.getByRole("dialog", { name: "New user" });
  await dialog.getByLabel("Username").fill(name);
  await dialog.getByLabel("Initial password").fill(password);
  await dialog.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByText(name, { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Username").fill(name);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Your password" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Users" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "All agent access" })).toHaveCount(0);

  // A member still manages their own agent access, inside the member vocabulary.
  const card = page
    .locator("div.card-surface")
    .filter({ has: page.getByRole("heading", { name: "Interaction agent access" }) });
  await card.getByRole("button", { name: "New access key" }).click();
  const accessDialog = page.getByRole("dialog", { name: "New interaction agent access" });
  await accessDialog.getByLabel("Agent name").fill("member desktop");
  await expect(accessDialog.getByText("boards:write", { exact: true })).toHaveCount(0);
  await accessDialog.getByRole("button", { name: "Create access" }).click();
  await expect(page.getByRole("dialog", { name: "Copy this token now" })).toBeVisible();
  const token = await page.getByLabel("New API token").inputValue();
  expect(token.startsWith("trl_")).toBe(true);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(card.getByText("member desktop")).toBeVisible();
  await expect(card.getByText("never used")).toBeVisible();

  // The in-card guide is what a person follows at their own machine.
  await card.getByText("How do I connect my computer?").click();
  await expect(card.getByText("Copy the token.")).toBeVisible();
  await expect(card.getByRole("button", { name: "Copy this block" })).toBeVisible();
});

test("the last enabled administrator cannot be disabled", async ({ page }) => {
  await login(page);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Disable admin" }).click();
  await expect(
    page.getByText("At least one enabled administrator must remain"),
  ).toBeVisible();
});

test("disabling a person revokes the agent access they issued", async ({ page, browser }) => {
  await login(page);
  await page.goto("/settings");
  const name = uniqueName("owner").replace(/\s+/g, "-").toLowerCase();
  const password = "owner-password-1";

  await page.getByRole("button", { name: "New user" }).click();
  const createDialog = page.getByRole("dialog", { name: "New user" });
  await createDialog.getByLabel("Username").fill(name);
  await createDialog.getByLabel("Initial password").fill(password);
  await createDialog.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByText(name, { exact: false })).toBeVisible();

  const member = await browser.newContext();
  const memberPage = await member.newPage();
  await memberPage.goto("/login");
  await memberPage.getByLabel("Username").fill(name);
  await memberPage.getByLabel("Password").fill(password);
  await memberPage.getByRole("button", { name: "Sign in" }).click();
  await expect(memberPage.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();

  await memberPage.goto("/settings");
  const membershipCard = memberPage
    .locator("div.card-surface")
    .filter({ has: memberPage.getByRole("heading", { name: "Interaction agent access" }) });
  await membershipCard.getByRole("button", { name: "New access key" }).click();
  const accessDialog = memberPage.getByRole("dialog", {
    name: "New interaction agent access",
  });
  await accessDialog.getByLabel("Agent name").fill("owner desktop");
  await accessDialog.getByRole("button", { name: "Create access" }).click();
  await expect(memberPage.getByRole("dialog", { name: "Copy this token now" })).toBeVisible();
  const token = await memberPage.getByLabel("New API token").inputValue();
  await memberPage.getByRole("button", { name: "Done" }).click();
  await expect(membershipCard.getByText("owner desktop")).toBeVisible();

  // The administrator sees the count and revokes it by disabling the account.
  await page.reload();
  const row = page.locator("li").filter({ hasText: name });
  await expect(row.getByText("1 agent access")).toBeVisible();
  await page.getByRole("button", { name: `Disable ${name}` }).click();
  await expect(row.getByText("0 agent accesses")).toBeVisible();

  // The key the member issued no longer authenticates.
  const probe = await memberPage.request.get("/api/v1/credentials/mine", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(probe.status()).toBe(401);
  await member.close();
});

test("an invitation link lets a person set their own password", async ({ page, browser }) => {
  await login(page);
  await page.goto("/settings");
  const name = uniqueName("invited").replace(/\s+/g, "-").toLowerCase();

  await page.getByRole("button", { name: "New user" }).click();
  const createDialog = page.getByRole("dialog", { name: "New user" });
  await createDialog.getByLabel("Username").fill(name);
  await createDialog.getByLabel("Initial password").fill("placeholder-123");
  await createDialog.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByText(name, { exact: false })).toBeVisible();

  await page.getByRole("button", { name: `Create an invitation link for ${name}` }).click();
  const inviteDialog = page.getByRole("dialog", { name: `Invitation link for ${name}` });
  const link = await inviteDialog.getByLabel("Link").inputValue();
  expect(link).toContain("/enrol?token=");
  await inviteDialog.getByRole("button", { name: "Done" }).click();

  // A fresh context: the administrator must not be signed in on the invited browser.
  const invited = await browser.newContext();
  const invitedPage = await invited.newPage();
  await invitedPage.goto(link);
  await expect(invitedPage.getByRole("heading", { name: "Choose your password" })).toBeVisible();
  await invitedPage.getByLabel("Password", { exact: true }).fill("claimed-by-the-person-9");
  await invitedPage.getByLabel("Repeat password").fill("claimed-by-the-person-9");
  await invitedPage.getByRole("button", { name: "Set password and sign in" }).click();
  await expect(invitedPage.getByRole("heading", { name: "Boards", level: 1 })).toBeVisible();
  await expect(invitedPage.getByText(name, { exact: false })).toBeVisible();

  // The link is single use: opening it again does not sign anyone in.
  const replay = await browser.newContext();
  const replayPage = await replay.newPage();
  await replayPage.goto(link);
  await replayPage.getByLabel("Password", { exact: true }).fill("another-password-77");
  await replayPage.getByLabel("Repeat password").fill("another-password-77");
  await replayPage.getByRole("button", { name: "Set password and sign in" }).click();
  await expect(replayPage.getByText("already used")).toBeVisible();

  await invited.close();
  await replay.close();
});
