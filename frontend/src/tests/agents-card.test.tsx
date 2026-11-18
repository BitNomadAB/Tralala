import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AgentsCard } from "@/features/settings/AgentsCard";
import { removalFocusTarget } from "@/features/settings/removalFocus";
import type { Agent } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";

const TESTED = "2026-11-03T08:00:00Z";

function agent(overrides: Partial<Agent> & Pick<Agent, "id" | "name">): Agent {
  return {
    description: "",
    role_template_id: null,
    role_template_name: null,
    role_template_scope: "board",
    role_template_updated_at: null,
    has_role_override: false,
    connection_type: "openai_compatible",
    base_url: "http://192.168.1.20:8080/v1",
    model: "local-model",
    has_api_key: false,
    api_key_hint: null,
    temperature: null,
    max_output_tokens: null,
    timeout_seconds: 180,
    enabled: true,
    last_test_status: null,
    last_test_message: null,
    last_tested_at: null,
    supports_tools: false,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...overrides,
  };
}

/** The card over `agents`; deleting one removes it from what the server lists. */
function renderCard(agents: Agent[]) {
  server.use(
    http.get(apiPath("/agents"), () => ok(agents)),
    http.delete(apiPath("/agents/:id"), ({ params }) => {
      agents.splice(
        agents.findIndex((entry) => entry.id === params.id),
        1,
      );
      return ok({ deleted: true });
    }),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <AgentsCard />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** The list entry of the agent named `name`. */
async function entry(name: string): Promise<HTMLElement> {
  const item = (await screen.findByText(name)).closest("li");
  if (!item) throw new Error(`no list entry for ${name}`);
  return item;
}

describe("the agent list in Settings", () => {
  it("says which agents read repositories with tools, once a connection test has said so", async () => {
    renderCard([
      agent({
        id: "reader",
        name: "Reader",
        last_test_status: "connected",
        last_tested_at: TESTED,
        supports_tools: true,
      }),
      agent({ id: "plain", name: "Plain", last_test_status: "connected", last_tested_at: TESTED }),
      agent({ id: "untested", name: "Untested" }),
    ]);

    const reader = within(await entry("Reader"));
    expect(reader.getByText("reads repositories with tools")).toHaveAttribute(
      "title",
      "A run lets this agent read the board's repositories itself",
    );
    expect(reader.queryByText("no tool calling")).not.toBeInTheDocument();

    const plain = within(await entry("Plain"));
    expect(plain.getByText("no tool calling")).toHaveAttribute(
      "title",
      "A run sends this agent a fixed snapshot of the board's repositories",
    );
    expect(plain.queryByText("reads repositories with tools")).not.toBeInTheDocument();

    // Before the first test nothing is known, so nothing is claimed.
    const untested = within(await entry("Untested"));
    expect(untested.getByText("not tested")).toBeInTheDocument();
    expect(untested.queryByText("no tool calling")).not.toBeInTheDocument();
    expect(untested.queryByText("reads repositories with tools")).not.toBeInTheDocument();
  });

  it("opens New agent and Edit as links, so they can open in a new tab", async () => {
    renderCard([agent({ id: "reader", name: "Reader" })]);

    expect(await screen.findByRole("link", { name: "Edit Reader" })).toHaveAttribute(
      "href",
      "/settings/agents/reader",
    );
    expect(screen.getByRole("link", { name: "New agent" })).toHaveAttribute(
      "href",
      "/settings/agents/new",
    );
  });

  it("moves focus to the next agent once one is deleted, and to the heading after the last", async () => {
    renderCard([agent({ id: "first", name: "First" }), agent({ id: "second", name: "Second" })]);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete First" }));
    await user.click(screen.getByRole("button", { name: "Delete agent" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Edit Second" })).toHaveFocus());
    await waitFor(() => expect(screen.queryByText("First")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete Second" }));
    await user.click(screen.getByRole("button", { name: "Delete agent" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "AI agents" })).toHaveFocus());
  });
});

describe("removalFocusTarget", () => {
  const control = (id: string) => `edit-${id}`;

  it("picks the next entry, else the previous one, else the heading", () => {
    expect(removalFocusTarget(["a", "b", "c"], "a", control, "heading")).toBe("edit-b");
    expect(removalFocusTarget(["a", "b", "c"], "c", control, "heading")).toBe("edit-b");
    expect(removalFocusTarget(["a"], "a", control, "heading")).toBe("heading");
    expect(removalFocusTarget(["a"], "gone", control, "heading")).toBe("heading");
  });
});
