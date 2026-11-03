import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AgentEditorPage } from "@/features/settings/AgentEditorPage";
import { apiPath, failure, ok } from "./msw/envelope";
import { server } from "./msw/server";

/** A new agent's form, filled in far enough to be saved, then saved against `answer`. */
async function saveNewAgent(answer: () => ReturnType<typeof failure>) {
  server.use(
    http.get(apiPath("/role-templates"), () => ok([])),
    http.post(apiPath("/agents"), answer),
  );
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
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("API base URL"), "http://127.0.0.1:8080/v1");
  await user.type(screen.getByLabelText("Role prompt override (optional)"), "You review.");
  await user.type(screen.getByLabelText("Maximum answer length (tokens)"), "999999");
  await user.click(screen.getByRole("button", { name: "Save agent" }));
  expect(await screen.findByText("Could not save agent")).toBeInTheDocument();
}

describe("the agent form when a save is refused", () => {
  it("names the field in the toast and marks the input the refusal names", async () => {
    await saveNewAgent(() =>
      failure(422, "validation_failed", "Must be at most 8192 for this preset", {
        field: "max_output_tokens",
      }),
    );

    expect(
      screen.getByText("max_output_tokens: Must be at most 8192 for this preset"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Maximum answer length (tokens)")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText("API base URL")).not.toHaveAttribute("aria-invalid");
  });

  it("shows the message as before and marks nothing when the refusal names no field", async () => {
    await saveNewAgent(() => failure(409, "conflict", "An agent with this name already exists"));

    expect(screen.getByText("An agent with this name already exists")).toBeInTheDocument();
    expect(screen.getByLabelText("Maximum answer length (tokens)")).not.toHaveAttribute(
      "aria-invalid",
    );
  });
});
