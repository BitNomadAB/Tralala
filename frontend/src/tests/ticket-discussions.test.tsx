import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NO_ASKABLE_AGENT } from "@/features/discussions/inboxRules";
import { formatDate } from "@/lib/utils";
import { CARD_ID, ticketCard } from "./msw/cards";
import { discussion, DISCUSSION_ID, QUESTION } from "./msw/discussions";
import { MEMBER } from "./msw/session";
import { ASKABLE, askedThread, ticketThread } from "./msw/ticketDiscussions";
import { LOOP_URL as DISCUSSION_LOOP_URL, renderDiscussion } from "./renderDiscussion";
import { LOOP_URL, renderTicket, TICKET_URL } from "./renderTicket";

const ASKED = formatDate(discussion().created_at);

/** Where the router is; read by selector, since an open dialog hides the probe from the a11y tree. */
function location() {
  const read = (name: string) =>
    document.querySelector(`output[aria-label="${name}"]`)?.textContent ?? null;
  return { path: read("Location"), query: read("Query") };
}

const THREADS = [
  ticketThread(
    "t-decided",
    50,
    { go: 0, stop: 2 },
    {
      status: "vetoed",
      decided_by_name: "Grace Hopper",
    },
  ),
  ticketThread("t-old-wait", 10, { go: 2, stop: 1 }),
  ticketThread("t-new-wait", 30, { go: 1, stop: 0 }),
  ticketThread("t-running", 40, null, { run_state: "running", round_count: 1, max_rounds: 3 }),
];

async function openTab(user: Awaited<ReturnType<typeof renderTicket>>["user"], count: number) {
  await user.click(await screen.findByRole("tab", { name: `Discussions ${String(count)}` }));
  return screen.findByRole("list", { name: "Discussions" });
}

describe("the Ticket's Discussions tab", () => {
  it("counts the Ticket's discussions and lists them: decision first, then running, then decided", async () => {
    const { user } = await renderTicket(ticketCard(), LOOP_URL, { discussions: THREADS });
    const tabs = screen.getByRole("tablist", { name: "Activity" });
    await waitFor(() =>
      expect(
        within(tabs)
          .getAllByRole("tab")
          .map((tab) => tab.textContent),
      ).toEqual(["Comments", "Discussions 4", "History", "Work"]),
    );
    const list = await openTab(user, 4);
    const rows = within(list).getAllByRole("link");
    expect(rows.map((row) => row.textContent)).toEqual([
      `Yes, with conditionsQuestion t-new-wait?Waits for your decision4 agents · 1 for · round 2 of 4 · asked by ${MEMBER.name} · ${ASKED}`,
      `Yes, with conditionsQuestion t-old-wait?Waits for your decision4 agents · 2 for · 1 against · round 2 of 4 · asked by ${MEMBER.name} · ${ASKED}`,
      `Agents are answeringQuestion t-running?Waits for the agents4 agents · round 1 of 3 · asked by ${MEMBER.name} · ${ASKED}`,
      `Yes, with conditionsQuestion t-decided?Vetoed by Grace Hopper4 agents · 2 against · round 2 of 4 · asked by ${MEMBER.name} · ${ASKED}`,
    ]);
  });

  it("opens a row's discussion in the Ticket's dialog over the Kanban", async () => {
    const { user } = await renderTicket(ticketCard(), LOOP_URL, { discussions: THREADS });
    const list = await openTab(user, 4);
    await user.click(within(list).getByRole("link", { name: /Question t-old-wait\?/ }));
    expect(location().path).toBe(LOOP_URL);
    expect(location().query).toBe(`?card=${CARD_ID}&discussion=t-old-wait`);
  });

  it("links a row to the discussion's page on the Ticket's page", async () => {
    const { user } = await renderTicket(ticketCard(), TICKET_URL, { discussions: THREADS });
    const list = await openTab(user, 4);
    expect(within(list).getByRole("link", { name: /Question t-running\?/ })).toHaveAttribute(
      "href",
      `${TICKET_URL}/discussions/t-running`,
    );
  });

  it("says when there is none, and its button opens Ask the agents", async () => {
    const { user } = await renderTicket(ticketCard(), LOOP_URL, { agents: ASKABLE });
    await user.click(await screen.findByRole("tab", { name: "Discussions 0" }));
    const panel = screen.getByRole("tabpanel", { name: "Discussions 0" });
    expect(panel).toHaveTextContent("No discussion yet. Ask the agents what they think.");
    await user.click(within(panel).getByRole("button", { name: "Ask the agents" }));
    expect(await screen.findByRole("dialog", { name: "Ask the agents" })).toBeInTheDocument();
  });

  it("offers Ask the agents in Activity's header and under More, never in the primary row", async () => {
    const { user } = await renderTicket(ticketCard(), LOOP_URL, { agents: ASKABLE });
    const activity = screen.getByRole("region", { name: "Activity" });
    expect(within(activity).getByRole("button", { name: "Ask the agents" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Ask the agents" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "More actions" }));
    const menu = screen.getByRole("list", { name: "More actions" });
    await user.click(within(menu).getByRole("button", { name: "Ask the agents" }));
    expect(await screen.findByRole("dialog", { name: "Ask the agents" })).toBeInTheDocument();
  });

  it("hides Ask the agents on a read-only Ticket and keeps the list", async () => {
    const { user } = await renderTicket(ticketCard(), LOOP_URL, {
      loop: { stage: "completed" },
      agents: ASKABLE,
    });
    await user.click(await screen.findByRole("tab", { name: "Discussions 0" }));
    expect(screen.getByRole("tabpanel", { name: "Discussions 0" })).toHaveTextContent(
      "No discussion yet.",
    );
    expect(screen.queryByRole("button", { name: "Ask the agents" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "More actions" }));
    const menu = screen.getByRole("list", { name: "More actions" });
    expect(within(menu).queryByRole("button", { name: "Ask the agents" })).toBeNull();
  });
});

describe("Ask the agents", () => {
  it("preselects every agent with its role, asks, starts one round and opens the discussion", async () => {
    const asked = askedThread();
    const { api, user } = await renderDiscussion(
      asked,
      `${DISCUSSION_LOOP_URL}?card=${CARD_ID}`,
      [],
      { agents: ASKABLE, heading: ticketCard().title },
    );
    api.state.next.start = askedThread({ run_state: "running" });
    await user.click(screen.getByRole("button", { name: "Ask the agents" }));
    const dialog = await screen.findByRole("dialog", { name: "Ask the agents" });
    const boxes = await within(dialog).findAllByRole("checkbox");
    expect(boxes.map((box) => box.closest("label")?.textContent)).toEqual([
      "Alpha Product Owner",
      "Bravo Backend Developer",
      "Charlie",
    ]);
    boxes.forEach((box) => expect(box).toBeChecked());
    const ask = within(dialog).getByRole("button", { name: "Ask" });
    expect(ask).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Question"), `  ${QUESTION}  `);
    await user.click(within(dialog).getByRole("checkbox", { name: "Bravo Backend Developer" }));
    await user.click(ask);

    expect(await screen.findByRole("dialog", { name: QUESTION })).toBeInTheDocument();
    const sign = screen.getByRole("region", { name: "Tralala's suggestion" });
    await waitFor(() => expect(sign).toHaveTextContent("Agents are answering· round 1 of 3"));
    expect(location().query).toBe(`?card=${CARD_ID}&discussion=${DISCUSSION_ID}`);
    expect(api.state.bodies.map(({ route, body }) => ({ route, body }))).toEqual([
      {
        route: "create",
        body: {
          card_id: CARD_ID,
          title: QUESTION,
          goal: QUESTION,
          mode: "roundtable",
          participant_ids: ["agent-Alpha", "agent-Charlie"],
        },
      },
      { route: "start", body: { rounds: 1, background: true } },
    ]);
    expect(api.state.bodies.every((write) => write.csrf === "csrf-discussion")).toBe(true);
  });

  it("says no agent can answer, links to Settings and keeps Ask disabled", async () => {
    const { user } = await renderTicket(ticketCard(), LOOP_URL, { agents: [] });
    await user.click(screen.getByRole("button", { name: "Ask the agents" }));
    const dialog = await screen.findByRole("dialog", { name: "Ask the agents" });
    expect(await within(dialog).findByText(NO_ASKABLE_AGENT)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Open Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
    await user.type(within(dialog).getByLabelText("Question"), QUESTION);
    expect(within(dialog).getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
  });
});
