import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { DiscussionView } from "@/features/discussions/DiscussionView";
import { announcer } from "./announcer";
import { ended, event, RUN_ID, talkEvents, talking } from "./msw/discussionRuns";
import { discussionHandlers, DISCUSSION_ID, QUESTION } from "./msw/discussions";
import { BOARD_ID, LOOP_ID } from "./msw/loops";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";
import { MODAL_URL, PAGE_URL, renderDiscussion } from "./renderDiscussion";

/**
 * Everything the polite announcer says from now on, one text after the other (texts sent in the
 * same moment are read together, so they arrive as one).
 */
function heard(): { text: () => string } {
  const texts: string[] = [];
  const region = announcer();
  const observer = new MutationObserver(() => {
    if (region.textContent) texts.push(region.textContent);
  });
  observer.observe(region, { childList: true, characterData: true, subtree: true });
  return { text: () => texts.join(" | ") };
}

function heading() {
  return screen.getByRole("heading", { name: QUESTION });
}

describe("focus in a discussion", () => {
  it("stays on Let them talk it out when the talk starts, and says the talk started", async () => {
    const { user, api } = await renderDiscussion();
    const said = heard();
    await user.click(screen.getByRole("button", { name: "Let them talk it out" }));
    api.state.next.start = talking();
    await user.click(screen.getByRole("button", { name: "Start" }));
    const talk = await screen.findByRole("button", {
      name: "Let them talk it out",
      description: "The agents are already answering",
    });
    await waitFor(() => expect(talk).toHaveFocus());
    await waitFor(() =>
      expect(said.text()).toContain(
        "Talk started: the agents answer each other for up to 2 rounds.",
      ),
    );
    await waitFor(() => expect(said.text()).toContain("Agents are answering, round 3 of 4"));
  });

  it("goes to the heading once Stop leaves with the run, and says how the run ended", async () => {
    const { user, api } = await renderDiscussion(talking(), MODAL_URL, talkEvents());
    const said = heard();
    api.state.next.stop = ended({ status: "stopped", stop_reason: "human_stop" });
    api.state.events = [
      ...talkEvents(),
      event(7, "run_finished", { run_id: RUN_ID, run_status: "stopped" }, MEMBER.name),
    ];
    await user.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Stop" })).toBeNull());
    expect(heading()).toHaveFocus();
    await waitFor(() =>
      expect(said.text()).toMatch(
        /Stopped( by Ada Member)?\. Tralala's suggestion after round 2: Yes, with conditions\./,
      ),
    );
  });

  it("goes to the heading once the decision is taken", async () => {
    const { user } = await renderDiscussion();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const review = screen.getByRole("dialog", { name: "Approve outcome" });
    await user.click(within(review).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Approve" })).toBeNull());
    await waitFor(() => expect(heading()).toHaveFocus());
  });

  it("keeps focus on the rail's Pause as it turns into Resume", async () => {
    const { user, api } = await renderDiscussion(talking(), MODAL_URL, talkEvents());
    const rail = screen.getByRole("complementary", { name: "Status and facts" });
    await user.click(within(rail).getByText("More"));
    api.state.next.pause = talking("paused");
    const pause = within(rail).getByRole("button", { name: "Pause while they talk" });
    await user.click(pause);
    await waitFor(() => expect(pause).toHaveAccessibleName("Resume"));
    expect(pause).toHaveFocus();
  });

  it("says the reply was sent and that the agents answer it", async () => {
    const { user, api } = await renderDiscussion();
    const said = heard();
    api.state.next.messages = talking();
    await user.type(screen.getByRole("textbox", { name: "Reply" }), "And if it is wrong?");
    const ask = screen.getByRole("button", { name: "Ask again" });
    await user.click(ask);
    await waitFor(() => expect(said.text()).toContain("Agents are answering, round 3 of 4"));
    expect(said.text()).toContain("Reply sent");
    expect(ask).toHaveFocus();
    expect(ask).toHaveAttribute("aria-disabled", "true");
  });

  it("gives focus to the heading when the host asks for it on opening", async () => {
    server.use(...discussionHandlers().handlers);
    const auth = {
      actor: MEMBER,
      loading: false,
      login: () => Promise.resolve(MEMBER),
      logout: () => Promise.resolve(),
      refresh: () => Promise.resolve(MEMBER),
      signOutLocally: () => undefined,
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthContext.Provider value={auth}>
          <ToastProvider>
            <MemoryRouter>
              <DiscussionView
                boardId={BOARD_ID}
                discussionId={DISCUSSION_ID}
                loopId={LOOP_ID}
                host="modal"
                focusOnOpen
              />
            </MemoryRouter>
          </ToastProvider>
        </AuthContext.Provider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(heading()).toHaveFocus());
  });
});

describe("the headings of a discussion", () => {
  function levels(name: string) {
    return screen.getByRole("heading", { name }).tagName;
  }

  it("put the sections at h2 under the page's h1", async () => {
    await renderDiscussion(undefined, PAGE_URL);
    expect(levels(QUESTION)).toBe("H1");
    expect(levels("Who stands where")).toBe("H2");
    expect(levels("Status")).toBe("H2");
    expect(levels("Facts")).toBe("H2");
  });

  it("put the sections at h3 under the dialog's h2, with the rail's parts as groups", async () => {
    const { user } = await renderDiscussion();
    expect(levels(QUESTION)).toBe("H2");
    expect(levels("Who stands where")).toBe("H3");
    expect(levels("Status")).toBe("H3");
    await user.click(screen.getByRole("button", { name: "Details from Alpha" }));
    expect(levels("For")).toBe("H4");
    expect(screen.queryByRole("region", { name: "Status" })).toBeNull();
    expect(screen.getByRole("group", { name: "Facts" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tralala's suggestion" })).toBeInTheDocument();
  });
});
