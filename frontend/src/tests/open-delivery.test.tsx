import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopCompletionDialog } from "@/features/loops/LoopCompletionDialog";
import type { LoopReadiness, OpenDeliveryTicket } from "@/lib/types";
import { isRecord } from "./msw/cards";
import { apiPath, failure, ok } from "./msw/envelope";
import { BOARD_ID, LOOP, LOOP_PATH, NOW } from "./msw/loops";
import { server } from "./msw/server";
import { READINESS } from "./msw/ticketView";

const OPEN: OpenDeliveryTicket[] = [
  {
    id: "card-7",
    ticket_key: "SES-1-PH02-003",
    title: "Switch payments off",
    completed_at: null,
    archived_at: null,
  },
  {
    id: "card-8",
    ticket_key: "SES-1-PH03-001",
    title: "Write the runbook",
    completed_at: null,
    archived_at: NOW,
  },
];

/** The dialog over a Loop whose readiness lists `open`, and every acceptance it sends. */
function renderDialog(open: OpenDeliveryTicket[], { isHuman = true } = {}) {
  const readiness: LoopReadiness = { ...READINESS, open_delivery: open };
  const sent: Record<string, unknown>[] = [];
  server.use(
    http.get(apiPath(`${LOOP_PATH}/readiness`), () => ok(readiness)),
    http.post(apiPath(`${LOOP_PATH}/completion`), async ({ request }) => {
      const body: unknown = await request.json();
      if (isRecord(body)) sent.push(body);
      return ok({});
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <LoopCompletionDialog
          boardId={BOARD_ID}
          loop={{ ...LOOP, stage: "in_progress" }}
          open
          isHuman={isHuman}
          onClose={() => undefined}
          onChanged={() => undefined}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { sent, user: userEvent.setup() };
}

const accept = () => screen.getByRole("button", { name: "Accept implementation" });

describe("accepting the implementation with delivery Tickets that are not done", () => {
  it("names them and holds Accept up until the person accepts without them", async () => {
    const { sent, user } = renderDialog(OPEN);
    const reason = await screen.findByText("2 delivery Tickets are not done.");
    expect(screen.getByText("SES-1-PH02-003").parentElement).toHaveTextContent(
      "SES-1-PH02-003 Switch payments off",
    );
    expect(screen.getByText("SES-1-PH03-001").parentElement).toHaveTextContent(
      "SES-1-PH03-001 Write the runbook (archived)",
    );
    // Held, not disabled: it stays in the tab order and says why (WCAG 2.4.3, 3.3.2).
    expect(accept()).toHaveAttribute("aria-disabled", "true");
    expect(accept()).not.toBeDisabled();
    expect(accept()).toHaveAttribute("aria-describedby", reason.id);
    await user.click(accept());
    expect(sent).toEqual([]);
  });

  it("accepts without them once the person says so, and can take that back", async () => {
    const { sent, user } = renderDialog(OPEN);
    const without = await screen.findByRole("button", { name: "Accept without them" });
    await user.click(without);
    expect(screen.getByText("Accepting without 2 delivery Tickets.")).toBeInTheDocument();
    expect(screen.getByText(/marked Not done and never\s+counts as done/)).toBeInTheDocument();
    // The same button, now Undo, kept the focus.
    const undo = screen.getByRole("button", { name: "Undo" });
    expect(undo).toBe(without);
    expect(undo).toHaveFocus();
    expect(accept()).not.toHaveAttribute("aria-disabled");

    await user.click(undo);
    expect(screen.getByText("2 delivery Tickets are not done.")).toBeInTheDocument();
    expect(accept()).toHaveAttribute("aria-disabled", "true");

    await user.click(screen.getByRole("button", { name: "Accept without them" }));
    await user.click(accept());
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ accepted: true, accept_unfinished: true });
    expect(await screen.findByText("Implementation accepted")).toBeInTheDocument();
  });

  it("speaks of one Ticket as one", async () => {
    const { user } = renderDialog(OPEN.slice(0, 1));
    expect(await screen.findByText("1 delivery Ticket is not done.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Accept without it" }));
    expect(screen.getByText("Accepting without 1 delivery Ticket.")).toBeInTheDocument();
  });

  it("asks for nothing when every delivery Ticket is done", async () => {
    const { sent, user } = renderDialog([]);
    await user.click(accept());
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ accept_unfinished: false });
    expect(screen.queryByText(/not done\.$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Accept without/ })).not.toBeInTheDocument();
  });

  it("leaves the choice to a signed-in person", async () => {
    renderDialog(OPEN, { isHuman: false });
    expect(await screen.findByRole("button", { name: "Accept without them" })).toBeDisabled();
    expect(accept()).toBeDisabled();
  });

  it("shows the Tickets a refusal names when they were not known to be open", async () => {
    const { user } = renderDialog([]);
    let asked = 0;
    server.use(
      http.get(apiPath(`${LOOP_PATH}/readiness`), () => {
        asked += 1;
        return ok({ ...READINESS, open_delivery: OPEN.slice(0, 1) });
      }),
      http.post(apiPath(`${LOOP_PATH}/completion`), () =>
        failure(409, "ticket_blocked", "Delivery Tickets are still open"),
      ),
    );
    await user.click(accept());
    expect(await screen.findByText("Could not accept")).toBeInTheDocument();
    expect(await screen.findByText("1 delivery Ticket is not done.")).toBeInTheDocument();
    expect(asked).toBeGreaterThan(0);
  });
});
