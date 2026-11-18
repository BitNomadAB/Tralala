import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnnounceContext, type Announce } from "@/components/ui/useAnnounce";
import { runView } from "@/features/discussions/runEvents";
import { useDiscussionNotices } from "@/features/discussions/useDiscussionNotices";
import type { Discussion, DiscussionEvent } from "@/lib/types";
import { talkEvents, talking } from "./msw/discussionRuns";
import { discussion } from "./msw/discussions";

function Notices({
  thread,
  events,
  ready,
}: {
  thread: Discussion;
  events: DiscussionEvent[];
  ready: boolean;
}) {
  useDiscussionNotices(thread, runView(thread, events), ready);
  return null;
}

/** The hook under an announcer the test reads back. */
function renderNotices(thread: Discussion, ready: boolean) {
  const announce = vi.fn<Announce>();
  const view = (next: Discussion, events: DiscussionEvent[], isReady: boolean) => (
    <AnnounceContext.Provider value={announce}>
      <Notices thread={next} events={events} ready={isReady} />
    </AnnounceContext.Provider>
  );
  const { rerender } = render(view(thread, [], ready));
  return {
    announce,
    show: (next: Discussion, events: DiscussionEvent[], isReady = true) => {
      rerender(view(next, events, isReady));
    },
  };
}

describe("what the discussion view announces", () => {
  it("reads nothing out until the stored events are in, and nothing of what they held", () => {
    const { announce, show } = renderNotices(discussion(), false);
    show(talking(), talkEvents(), false);
    show(talking(), talkEvents());
    expect(announce).not.toHaveBeenCalled();
  });

  it("reads out what changed after the first look", () => {
    const { announce, show } = renderNotices(discussion(), true);
    expect(announce).not.toHaveBeenCalled();
    show(talking(), []);
    expect(announce).toHaveBeenCalledWith("Agents are answering, round 3 of 4");
  });
});
