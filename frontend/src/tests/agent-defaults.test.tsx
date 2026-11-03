import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AgentEditorPage } from "@/features/settings/AgentEditorPage";
import { answerLengthProblem, emptyAgentForm } from "@/features/settings/agentForm";
import type { ProviderPreset } from "@/lib/providers";
import { apiPath, failure, ok } from "./msw/envelope";
import { server } from "./msw/server";

function renderNewAgent() {
  server.use(http.get(apiPath("/role-templates"), () => ok([])));
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/settings/agents/new"]}>
          <Routes>
            <Route path="/settings/agents/:agentId" element={<AgentEditorPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const CAPPED: ProviderPreset = {
  id: "capped",
  label: "Capped",
  baseUrl: "https://llm.example.com/v1",
  model: "m",
  baseUrlFixed: true,
  requiresApiKey: true,
  requiresModel: true,
  maxOutputTokens: 8192,
};

const UNCAPPED: ProviderPreset = {
  id: "uncapped",
  label: "Uncapped",
  baseUrl: "",
  model: "",
  baseUrlFixed: false,
  requiresApiKey: false,
  requiresModel: false,
};

describe("a new agent's defaults", () => {
  it("waits 180 s and leaves the answer length and the temperature to the provider", async () => {
    const sent: unknown[] = [];
    server.use(
      http.post(apiPath("/agents"), async ({ request }) => {
        sent.push(await request.json());
        return failure(409, "conflict", "stop here");
      }),
    );
    const user = renderNewAgent();
    expect(screen.getByLabelText("Timeout (seconds)")).toHaveValue(180);
    expect(screen.getByLabelText("Maximum answer length (tokens)")).toHaveValue(null);
    expect(screen.getByLabelText("Temperature")).toHaveAttribute("placeholder", "provider default");
    expect(screen.getAllByText("Empty uses the provider's default.")).toHaveLength(2);

    await user.type(screen.getByLabelText("API base URL"), "http://192.168.1.20:8080/v1");
    await user.type(screen.getByLabelText("Role prompt override (optional)"), "You review.");
    await user.click(screen.getByRole("button", { name: "Save agent" }));
    expect(await screen.findByText("stop here")).toBeInTheDocument();
    expect(sent).toEqual([
      expect.objectContaining({
        timeout_seconds: 180,
        max_output_tokens: null,
        temperature: null,
      }),
    ]);
  });
});

describe("the answer length against a preset's cap", () => {
  const form = (maxTokens: string) => ({ ...emptyAgentForm(true), maxTokens });

  it("refuses a length above the cap and names the cap", () => {
    expect(answerLengthProblem(form("8193"), CAPPED)).toBe(
      "Capped answers at most 8,192 tokens; leave the field empty for its default.",
    );
  });

  it("accepts an empty field, the cap itself and any length where no cap is known", () => {
    expect(answerLengthProblem(form(""), CAPPED)).toBeNull();
    expect(answerLengthProblem(form("8192"), CAPPED)).toBeNull();
    expect(answerLengthProblem(form("2000000"), UNCAPPED)).toBeNull();
    expect(answerLengthProblem(form("2000000"), undefined)).toBeNull();
  });
});
