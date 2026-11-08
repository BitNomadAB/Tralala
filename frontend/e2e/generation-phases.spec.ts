import type http from "node:http";
import { expect, test } from "playwright/test";
import {
  BROKEN_MODEL,
  PATIENT_MODEL,
  PORT,
  received,
  SLOW_MODEL,
  startStandInModel,
  stopStandInModel,
  TOOL_MODEL,
} from "./stand-in-model";
import { boardWithLoop, csrfToken, login, openPlanDocument, showTab, uniqueName } from "./support";

/**
 * The progress panel is the run's process tree, written step by step, so the only honest way to test
 * it is a provider that answers slowly (`stand-in-model.ts`): fast enough to finish inside a journey
 * but slow enough that the intermediate steps are visible.
 */
let server: http.Server | null = null;

test.beforeAll(async () => {
  server = await startStandInModel();
});

test.afterAll(async () => {
  await stopStandInModel(server);
});

// The side panel only exists on a wide window; the compact one is what a laptop shows.
test.use({ viewport: { width: 1600, height: 900 } });

test.describe("generation progress", () => {
  test("shows the step it is on, then the draft, and locks the Generate button", async ({
    page,
  }) => {
    await login(page);
    const boardName = uniqueName("Progress journey");
    await boardWithLoop(page, boardName, "Session expiry");
    const headers = { "X-CSRF-Token": await csrfToken(page) };

    const templates = (await (await page.request.get("/api/v1/role-templates")).json()).data;
    const role =
      templates.find(
        (entry: { builtin_key?: string }) => entry.builtin_key === "analytics_agent",
      ) ?? templates[0];
    const agentName = uniqueName("Slow agent");
    const agent = await page.request.post("/api/v1/agents", {
      headers,
      data: {
        name: agentName,
        connection_type: "openai_compatible",
        base_url: `http://127.0.0.1:${PORT}/v1`,
        model: SLOW_MODEL,
        role_template_id: role.id,
      },
    });
    expect(agent.status()).toBe(201);
    const agentId = (await agent.json()).data.id as string;

    const dialog = await openPlanDocument(page, "Info");
    await dialog
      .getByLabel("Write or revise Info")
      .fill("Sessions must expire after 30 minutes of inactivity.");
    await dialog.getByRole("button", { name: "Save as new revision" }).click();
    await showTab(page, "Kanban");

    await page.reload();
    const analysis = await openPlanDocument(page, "Analysis");
    // Other specs leave agents behind and the default is "first by name", so pin this run's agent.
    await analysis.getByLabel("Generation agent").selectOption(agentId);
    const generate = analysis.getByRole("button", { name: /Generate analysis/ });
    await generate.click();

    // While the run is in flight the button is locked and glows, and the steps are on screen.
    const busy = analysis.getByRole("button", { name: /Generating/ });
    await expect(busy).toBeVisible();
    await expect(busy).toBeDisabled();
    await expect(busy).toHaveAttribute("data-generating", "true");

    const panel = page.locator('section[aria-label="Generation progress"]:visible');
    await expect(panel).toBeVisible();
    await expect(panel.getByText("Reading the Loop's documents")).toBeVisible();
    await expect(panel.getByText("Reading the repository")).toBeVisible();
    await expect(panel.getByText("Writing the analysis")).toBeVisible();
    await expect(panel.getByText("Checking the answer")).toBeVisible();
    // The tree grows in plain words: what the run read, and what it asked the model.
    await expect(panel.getByText("Read the Loop's Info (revision 1)")).toBeVisible();
    // The repository stage says what it actually got: this board links none, and a green tick
    // alone would look like the code had been read.
    await expect(
      panel.getByText("No enabled repository is linked to this board; no code was read"),
    ).toBeVisible();
    await expect(panel.getByText(`Asked ${agentName} for the analysis in one call`)).toBeVisible();

    // It finishes without a reload, and the draft replaces the progress panel.
    await expect(analysis.getByText(/Sessions never time out today/)).toBeVisible({
      timeout: 30_000,
    });
    await expect(analysis.getByRole("button", { name: /Generate analysis/ })).toBeEnabled();
    await expect(page.locator('section[aria-label="Generation progress"]:visible')).toHaveCount(0);
  });

  test("keeps the failed step on screen with the provider's own answer", async ({ page }) => {
    await login(page);
    const boardName = uniqueName("Failure journey");
    await boardWithLoop(page, boardName, "Session expiry");
    const headers = { "X-CSRF-Token": await csrfToken(page) };

    const templates = (await (await page.request.get("/api/v1/role-templates")).json()).data;
    const agentName = uniqueName("Broken agent");
    const agent = await page.request.post("/api/v1/agents", {
      headers,
      data: {
        name: agentName,
        connection_type: "openai_compatible",
        base_url: `http://127.0.0.1:${PORT}/v1`,
        model: BROKEN_MODEL,
        role_template_id: templates[0].id,
      },
    });
    expect(agent.status()).toBe(201);
    const agentId = (await agent.json()).data.id as string;

    const dialog = await openPlanDocument(page, "Info");
    await dialog.getByLabel("Write or revise Info").fill("Sessions must expire.");
    await dialog.getByRole("button", { name: "Save as new revision" }).click();
    await showTab(page, "Kanban");

    await page.reload();
    const analysis = await openPlanDocument(page, "Analysis");
    await analysis.getByLabel("Generation agent").selectOption(agentId);
    await analysis.getByRole("button", { name: /Generate analysis/ }).click();

    // The provider's sentence is on the failing step as JSON, and the panel stays until dismissed.
    const panel = page.locator('section[aria-label="Generation progress"]:visible');
    await expect(panel.locator("pre")).toContainText('"error_code": "provider_error"', {
      timeout: 30_000,
    });
    await expect(panel.locator("pre")).toContainText("Model Not Exist");
    await expect(panel.getByText("Writing the analysis")).toBeVisible();
    // The tree ends with what was not saved, and why.
    await expect(panel.getByText(/^Nothing was saved: The provider call failed/)).toBeVisible();
    await panel.getByRole("button", { name: "Dismiss progress" }).click();
    await expect(page.locator('section[aria-label="Generation progress"]:visible')).toHaveCount(0);
  });

  test("an agent whose model calls tools is marked so, and a board without code says so", async ({
    page,
  }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Tools journey"), "Session expiry");
    const headers = { "X-CSRF-Token": await csrfToken(page) };
    const templates = (await (await page.request.get("/api/v1/role-templates")).json()).data;
    const agentName = uniqueName("Tool agent");
    const agent = await page.request.post("/api/v1/agents", {
      headers,
      data: {
        name: agentName,
        connection_type: "openai_compatible",
        base_url: `http://127.0.0.1:${PORT}/v1`,
        model: TOOL_MODEL,
        role_template_id: templates[0].id,
      },
    });
    expect(agent.status()).toBe(201);
    const agentId = (await agent.json()).data.id as string;

    // The connection test offers one dummy tool; this model calls it, so the agent reads with tools.
    const tested = await page.request.post(`/api/v1/agents/${agentId}/test`, {
      headers,
      data: {},
    });
    expect(tested.status()).toBe(200);
    expect((await tested.json()).data.supports_tools).toBe(true);
    await page.goto("/settings");
    const row = page.getByRole("listitem").filter({ hasText: agentName });
    await expect(row.getByText("reads repositories with tools")).toBeVisible();

    await page.goBack();
    const dialog = await openPlanDocument(page, "Info");
    await dialog.getByLabel("Write or revise Info").fill("Sessions must expire.");
    await dialog.getByRole("button", { name: "Save as new revision" }).click();
    await showTab(page, "Kanban");
    await page.reload();
    const analysis = await openPlanDocument(page, "Analysis");
    await analysis.getByLabel("Generation agent").selectOption(agentId);
    await analysis.getByRole("button", { name: /Generate analysis/ }).click();

    // This board links no repository, so there is nothing to read: the tree says so, and the
    // model is asked in one call, without tools.
    const panel = page.locator('section[aria-label="Generation progress"]:visible');
    await expect(
      panel.getByText("No enabled repository is linked to this board; no code was read"),
    ).toBeVisible();
    await expect(analysis.getByText(/Sessions never time out today/)).toBeVisible({
      timeout: 30_000,
    });
    const generation = received.filter((entry) => entry.model === TOOL_MODEL && entry.analysis);
    expect(generation).toHaveLength(1);
    expect(generation[0]?.tools).toEqual([]);
  });

  test("asks before an Info save during a run, and keeps a late result for inspection", async ({
    page,
  }) => {
    await login(page);
    await boardWithLoop(page, uniqueName("Info guard journey"), "Session expiry");
    const headers = { "X-CSRF-Token": await csrfToken(page) };
    const templates = (await (await page.request.get("/api/v1/role-templates")).json()).data;
    const agent = await page.request.post("/api/v1/agents", {
      headers,
      data: {
        name: uniqueName("Patient agent"),
        connection_type: "openai_compatible",
        base_url: `http://127.0.0.1:${PORT}/v1`,
        model: PATIENT_MODEL,
        role_template_id: templates[0].id,
      },
    });
    expect(agent.status()).toBe(201);
    const agentId = (await agent.json()).data.id as string;

    // With no run in flight, a save is a plain save.
    const first = await openPlanDocument(page, "Info");
    await first.getByLabel("Write or revise Info").fill("Sessions must expire after 30 minutes.");
    await first.getByRole("button", { name: "Save as new revision" }).click();
    await expect(first.getByText("revision 1", { exact: true })).toBeVisible();
    await showTab(page, "Kanban");

    await page.reload();
    const dialog = await openPlanDocument(page, "Analysis");
    await dialog.getByLabel("Generation agent").selectOption(agentId);
    const generate = () => dialog.getByRole("button", { name: /Generate analysis/ }).click();
    const editInfoDuringRun = async (text: string) => {
      await expect(dialog.getByRole("button", { name: /Generating/ })).toBeDisabled();
      await dialog.getByRole("button", { name: "Info", exact: true }).click();
      await dialog.getByLabel("Write or revise Info").fill(text);
      await dialog.getByRole("button", { name: "Save as new revision" }).click();
      await expect(dialog.getByRole("alert")).toContainText("A generation run is in progress");
    };

    // "Cancel the run first" stops the run, then saves.
    await generate();
    await editInfoDuringRun("Sessions must expire after 20 minutes.");
    await dialog.getByRole("button", { name: "Cancel the run first" }).click();
    await expect(dialog.getByText("revision 2", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Analysis", exact: true }).click();
    await expect(dialog.getByText(/Last analysis run cancelled/)).toBeVisible();

    // "Save anyway" saves at once; the run then finishes on an Info that has changed, so its answer
    // is kept on the run, labelled as not promoted, instead of becoming the analysis.
    await generate();
    await editInfoDuringRun("Sessions must expire after 15 minutes.");
    await dialog.getByRole("button", { name: "Save anyway" }).click();
    await expect(dialog.getByText("revision 3", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Analysis", exact: true }).click();
    const kept = dialog.getByRole("region", { name: "Kept analysis result" });
    await expect(kept).toBeVisible({ timeout: 30_000 });
    await expect(kept.getByText("not promoted")).toBeVisible();
    await expect(kept).toContainText("Sessions never time out today.");
    await expect(dialog.getByText(/Last analysis run failed/)).toBeVisible();

    // Regenerating starts a new run from the current Info, and its draft replaces the kept one.
    await kept.getByRole("button", { name: "Regenerate from the current Info" }).click();
    await expect(dialog.getByRole("button", { name: /Generating/ })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: /Generate analysis/ })).toBeEnabled({
      timeout: 30_000,
    });
    await expect(kept).toHaveCount(0);
    await expect(dialog.getByText(/Sessions never time out today/)).toBeVisible();
  });
});
