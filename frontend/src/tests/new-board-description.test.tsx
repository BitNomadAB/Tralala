import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { NewBoardDialog } from "@/features/boards/NewBoardDialog";
import { templateReplaces } from "@/features/boards/useTemplateDescription";
import type { BoardTemplate } from "@/lib/types";
import { announcer } from "./announcer";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";

function template(id: string, name: string, description: string): BoardTemplate {
  return {
    id,
    name,
    description,
    lists: ["Backlog", "Done"],
    labels: [],
    created_at: "2026-11-01T09:00:00Z",
    updated_at: "2026-11-01T09:00:00Z",
    list_count: 2,
  };
}

const SCRUM = template("tpl-scrum", "Scrum", "Two-week sprints.");
const KANBAN = template("tpl-kanban", "Kanban", "A steady flow.");

async function renderDialog() {
  server.use(
    http.get(apiPath("/templates"), () => ok({ items: [SCRUM, KANBAN] })),
    http.get(apiPath("/repositories"), () => ok([])),
    http.get(apiPath("/agents"), () => ok([])),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <NewBoardDialog open onOpenChange={() => undefined} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: "Kanban" });
  return {
    user: userEvent.setup(),
    template: screen.getByLabelText("Start from"),
    description: screen.getByLabelText("Description"),
  };
}

describe("choosing a template for a new board", () => {
  it("fills in the template's description while the person has written none", async () => {
    const { user, template, description } = await renderDialog();
    await user.selectOptions(template, "tpl-scrum");
    expect(description).toHaveValue("Two-week sprints.");
    await user.selectOptions(template, "tpl-kanban");
    expect(description).toHaveValue("A steady flow.");
    await user.selectOptions(template, "");
    expect(description).toHaveValue("");
  });

  it("keeps the description the person wrote and offers the template's instead", async () => {
    const { user, template, description } = await renderDialog();
    await user.type(description, "Our own words.");
    await user.selectOptions(template, "tpl-scrum");

    expect(description).toHaveValue("Our own words.");
    expect(screen.getByText("The template has its own description; yours is kept.")).toBeVisible();
    await waitFor(() =>
      expect(announcer()).toHaveTextContent(
        "Your description is kept. The next button, Use the template's description, replaces it.",
      ),
    );
    // Back to the blank board: the words stay, and there is nothing to offer.
    await user.selectOptions(template, "");
    expect(description).toHaveValue("Our own words.");
    expect(
      screen.queryByRole("button", { name: "Use the template's description" }),
    ).not.toBeInTheDocument();
  });

  it("replaces the person's words only when they press Use the template's description", async () => {
    const { user, template, description } = await renderDialog();
    await user.selectOptions(template, "tpl-scrum");
    await user.clear(description);
    await user.type(description, "Sprints, but shorter.");
    await user.selectOptions(template, "tpl-kanban");
    expect(description).toHaveValue("Sprints, but shorter.");

    await user.click(screen.getByRole("button", { name: "Use the template's description" }));
    expect(description).toHaveValue("A steady flow.");
    expect(description).toHaveFocus();
    // Taken over, the template's text is the template's again: the next choice replaces it.
    await user.selectOptions(template, "tpl-scrum");
    expect(description).toHaveValue("Two-week sprints.");
  });
});

describe("templateReplaces", () => {
  it("replaces what the person did not write, an empty field, or the same text", () => {
    expect(templateReplaces("Two-week sprints.", false, "A steady flow.")).toBe(true);
    expect(templateReplaces("   ", true, "A steady flow.")).toBe(true);
    expect(templateReplaces("A steady flow.", true, "A steady flow.")).toBe(true);
    expect(templateReplaces("Our own words.", true, "A steady flow.")).toBe(false);
    expect(templateReplaces("Our own words.", true, "")).toBe(false);
  });
});
