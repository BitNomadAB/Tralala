import http from "node:http";
import { expect, test, type Page } from "playwright/test";
import { login, uniqueName } from "./support";

/**
 * A stand-in for an OpenAI-compatible endpoint. It answers `/models` with two names but refuses a
 * completion for any model it does not know, which is exactly the failure that used to hide behind
 * a green connection test.
 */
const PORT = 8099;
const KNOWN_MODEL = "stub-model-a";

let server: http.Server | null = null;
// What the last request carried, so the test can prove that "no key" really means no header.
let lastAuthorization: string | undefined;

test.beforeAll(async () => {
  server = http.createServer((request, response) => {
    const url = request.url ?? "";
    lastAuthorization = request.headers.authorization;
    if (request.method === "GET" && url.endsWith("/models")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ data: [{ id: KNOWN_MODEL }, { id: "stub-model-b" }] }));
      return;
    }
    if (request.method === "POST" && url.endsWith("/chat/completions")) {
      let body = "";
      request.on("data", (chunk) => (body += chunk));
      request.on("end", () => {
        let model = "";
        try {
          model = String(JSON.parse(body || "{}").model ?? "");
        } catch {
          model = "";
        }
        if (model === KNOWN_MODEL) {
          response.writeHead(200, { "content-type": "application/json" });
          response.end(JSON.stringify({ choices: [{ message: { content: "ok" } }] }));
          return;
        }
        response.writeHead(400, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: { message: "Model Not Exist" } }));
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

async function openSettings(page: Page) {
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "AI agents", level: 2 })).toBeVisible();
}

test.describe("agent connection test", () => {
  test("the form can be tested before it is saved, and a wrong model fails here", async ({
    page,
  }) => {
    await login(page);
    await openSettings(page);

    const before = (await (await page.request.get("/api/v1/agents")).json()).data.length;

    const agentName = uniqueName("Stub agent");
    await page.getByRole("button", { name: "New agent" }).click();
    await expect(page.getByRole("heading", { name: "New AI agent", level: 1 })).toBeVisible();
    await page.getByLabel("Agent name").fill(agentName);
    await page.getByLabel("Role template").selectOption({ label: "QA Engineer" });
    await page.getByLabel("API base URL").fill(`http://127.0.0.1:${PORT}/v1`);
    await page.getByLabel(/Model identifier/).fill("typo-model");

    const status = page.getByRole("status", { name: "Connection test result" });
    // A self-hosted endpoint: say so once, and no Authorization header is sent from then on.
    await page.getByLabel("This endpoint needs no key").check();
    await expect(page.getByLabel("API key (not used)")).toBeDisabled();

    // Test before saving: nothing is written, and the provider's own sentence comes back.
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(status).toContainText("Model Not Exist");
    await expect(status).toContainText("http_400");
    // The raw JSON is shown, so the answer reads the same whatever shape the provider used.
    await expect(status.locator("pre")).toContainText('"status": "http_400"');
    expect(lastAuthorization).toBeUndefined();
    await expect(page.getByText(/2 model\(s\) reported by the endpoint/)).toBeVisible();

    const afterFailedTest = (await (await page.request.get("/api/v1/agents")).json()).data.length;
    expect(afterFailedTest).toBe(before);

    await page.getByLabel(/Model identifier/).fill(KNOWN_MODEL);
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(status).toContainText("completed");
    await expect(status).toContainText(`Model ${KNOWN_MODEL} answered`);

    await page.getByRole("button", { name: "Save agent" }).click();
    await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
    await expect(page.getByText(agentName, { exact: true })).toBeVisible();

    await page.getByRole("button", { name: `Delete ${agentName}` }).click();
    const dialog = page.getByRole("dialog", { name: "Delete agent" });
    await dialog.getByRole("button", { name: "Delete agent" }).click();
    await expect(page.getByText(agentName, { exact: true })).toHaveCount(0);
  });

  test("the preset decides which fields the provider needs", async ({ page }) => {
    await login(page);
    await openSettings(page);
    await page.getByRole("button", { name: "New agent" }).click();
    await expect(page.getByRole("heading", { name: "New AI agent", level: 1 })).toBeVisible();

    // A hosted provider: fixed endpoint, key and model required, so saving is blocked without them.
    await page.getByLabel("Provider preset").selectOption({ label: "OpenAI" });
    await expect(page.getByLabel("This endpoint needs no key")).not.toBeChecked();
    await expect(page.getByLabel("API base URL")).toHaveValue("https://api.openai.com/v1");
    await expect(page.getByLabel("API base URL")).toHaveAttribute("readonly", "");
    await page.getByLabel("Role template").selectOption({ label: "QA Engineer" });
    await expect(page.getByLabel("API key (required)")).toBeVisible();
    await expect(page.getByLabel(/Model identifier \(required\)/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Save agent" })).toBeDisabled();

    // A local provider: same form, no key asked for, endpoint editable.
    await page.getByLabel("Provider preset").selectOption({ label: "Ollama (local)" });
    await expect(page.getByLabel("This endpoint needs no key")).toBeChecked();
    await expect(page.getByLabel("API base URL")).toHaveValue("http://127.0.0.1:11434/v1");
    await expect(page.getByLabel("API base URL")).not.toHaveAttribute("readonly", "");
    await expect(page.getByLabel("API key (not used)")).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save agent" })).toBeEnabled();
  });
});
