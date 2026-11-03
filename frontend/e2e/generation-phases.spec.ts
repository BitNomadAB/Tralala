import http from "node:http";
import { expect, test } from "playwright/test";
import { boardWithLoop, csrfToken, login, uniqueName } from "./support";

/**
 * A generation run is one background call, so the only honest way to test the progress panel is a
 * provider that answers slowly: one stand-in endpoint, fast enough to finish inside a journey but
 * slow enough that the intermediate steps are visible.
 */
const PORT = 8098;
const SLOW_MODEL = "slow-model";
const BROKEN_MODEL = "broken-model";
// Slow enough to leave the Info tab, edit and save while the run is still working.
const PATIENT_MODEL = "patient-model";

const ANALYSIS = {
  schema_version: 1,
  outcome: "Expire idle sessions",
  scope: ["idle timeout"],
  findings: [
    {
      id: "F-01",
      title: "The session table has no expiry column",
      category: "change",
      technical_detail: "backend/app/services/auth.py",
      plain_language: "Sessions never time out today.",
    },
  ],
  assumptions: [],
  open_questions: [],
  options: [],
  recommendation: "Add an expiry column.",
  verification: ["An idle session is rejected"],
  sources: [],
  repository_revision: "",
};

let server: http.Server | null = null;

test.beforeAll(async () => {
  server = http.createServer((request, response) => {
    const url = request.url ?? "";
    if (request.method === "GET" && url.endsWith("/models")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ data: [{ id: SLOW_MODEL }] }));
      return;
    }
    if (request.method === "POST" && url.endsWith("/chat/completions")) {
      let body = "";
      request.on("data", (chunk) => (body += chunk));
      request.on("end", () => {
        let model: string;
        try {
          model = String(JSON.parse(body || "{}").model ?? "");
        } catch {
          model = "";
        }
        if (model === BROKEN_MODEL) {
          response.writeHead(400, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: { message: "Model Not Exist" } }));
          return;
        }
        setTimeout(
          () => {
            response.writeHead(200, { "content-type": "application/json" });
            response.end(
              JSON.stringify({
                choices: [
                  { message: { content: "```json\n" + JSON.stringify(ANALYSIS) + "\n```" } },
                ],
                usage: { total_tokens: 21 },
              }),
            );
          },
          model === PATIENT_MODEL ? 6000 : 2500,
        );
      });
      return;
    }
    response.writeHead(404, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: { message: "not found" } }));
  });
  await new Promise<void>((resolve) => server?.listen(PORT, "127.0.0.1", () => resolve()));
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => {
    if (!server) return resolve();
    server.close(() => resolve());
  });
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

    await page.getByRole("button", { name: /^Info/ }).click();
    const dialog = page.getByRole("dialog", { name: /planning documents/ });
    await dialog
      .getByLabel("Write or revise Info")
      .fill("Sessions must expire after 30 minutes of inactivity.");
    await dialog.getByRole("button", { name: "Save as new revision" }).click();
    await page.getByRole("button", { name: "Close dialog" }).click();

    await page.reload();
    await page.getByRole("button", { name: "Analysis" }).click();
    const analysis = page.getByRole("dialog", { name: /planning documents/ });
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
    await expect(panel.getByText("Reading Info data")).toBeVisible();
    await expect(panel.getByText("Analysing repository")).toBeVisible();
    await expect(panel.getByText("Generating analysis")).toBeVisible();
    // The repository step says what it actually got: this board links none, and a green tick alone
    // would look like the code had been read.
    await expect(panel.getByText("No enabled repository is linked to this board.")).toBeVisible();
    // And the step itself is marked as skipped, not as done: a tick there claimed code was read.
    await expect(panel.getByText("Skipped: no code was sent to the model")).toBeVisible();

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

    await page.getByRole("button", { name: /^Info/ }).click();
    const dialog = page.getByRole("dialog", { name: /planning documents/ });
    await dialog.getByLabel("Write or revise Info").fill("Sessions must expire.");
    await dialog.getByRole("button", { name: "Save as new revision" }).click();
    await page.getByRole("button", { name: "Close dialog" }).click();

    await page.reload();
    await page.getByRole("button", { name: "Analysis" }).click();
    const analysis = page.getByRole("dialog", { name: /planning documents/ });
    await analysis.getByLabel("Generation agent").selectOption(agentId);
    await analysis.getByRole("button", { name: /Generate analysis/ }).click();

    // The provider's sentence is on the failing step as JSON, and the panel stays until dismissed.
    const panel = page.locator('section[aria-label="Generation progress"]:visible');
    await expect(panel.locator("pre")).toContainText('"error_code": "provider_error"', {
      timeout: 30_000,
    });
    await expect(panel.locator("pre")).toContainText("Model Not Exist");
    await expect(panel.getByText("Generating analysis")).toBeVisible();
    await panel.getByRole("button", { name: "Dismiss progress" }).click();
    await expect(page.locator('section[aria-label="Generation progress"]:visible')).toHaveCount(0);
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
    await page.getByRole("button", { name: /^Info/ }).click();
    const first = page.getByRole("dialog", { name: /planning documents/ });
    await first.getByLabel("Write or revise Info").fill("Sessions must expire after 30 minutes.");
    await first.getByRole("button", { name: "Save as new revision" }).click();
    await expect(first.getByText("revision 1", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Close dialog" }).click();

    await page.reload();
    await page.getByRole("button", { name: "Analysis" }).click();
    const dialog = page.getByRole("dialog", { name: /planning documents/ });
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
