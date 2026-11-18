import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { useFollowMovedBoard } from "@/features/boards/useFollowMovedBoard";
import { useFocusAfter } from "@/features/cards/useFocusAfter";
import { useFocusRescue } from "@/features/discussions/useFocusRescue";
import { useFocusBack } from "@/features/loops/useFocusBack";
import type { Board } from "@/lib/types";
import { board } from "./msw/boards";

const focus = (name: string) => {
  act(() => {
    screen.getByRole("button", { name }).focus();
  });
};

/** "Ask" requests the focus for "Later", which shows once `shown`. */
function FocusAfterHost({ shown }: { shown: boolean }) {
  const focusAfter = useFocusAfter();
  return (
    <>
      <button type="button" onClick={() => focusAfter(() => document.getElementById("later"))}>
        Ask
      </button>
      <button type="button" onClick={() => focusAfter(() => document.getElementById("other"))}>
        Ask for Other
      </button>
      <button type="button" id="other">
        Other
      </button>
      <button type="button">Elsewhere</button>
      {shown ? (
        <button type="button" id="later">
          Later
        </button>
      ) : null}
    </>
  );
}

describe("useFocusAfter", () => {
  it("waits until the control it asked for shows, then gives it the focus", async () => {
    const { rerender } = render(<FocusAfterHost shown={false} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask" }));
    expect(screen.getByRole("button", { name: "Ask" })).toHaveFocus();
    rerender(<FocusAfterHost shown />);
    expect(screen.getByRole("button", { name: "Later" })).toHaveFocus();
  });

  it("drops the request once the person put the focus somewhere else", async () => {
    const { rerender } = render(<FocusAfterHost shown={false} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask" }));
    focus("Elsewhere");
    rerender(<FocusAfterHost shown />);
    rerender(<FocusAfterHost shown={false} />);
    rerender(<FocusAfterHost shown />);
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });

  it("lets a later request replace an earlier one", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<FocusAfterHost shown={false} />);
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await user.click(screen.getByRole("button", { name: "Ask for Other" }));
    expect(screen.getByRole("button", { name: "Other" })).toHaveFocus();
    rerender(<FocusAfterHost shown />);
    expect(screen.getByRole("button", { name: "Other" })).toHaveFocus();
  });
});

/** "Reset" opens a confirmation whose "Confirm" leaves with it. */
function FocusBackHost({ open }: { open: boolean }) {
  useFocusBack(open, () => document.getElementById("reset"));
  return (
    <>
      <button type="button" id="reset">
        Reset
      </button>
      {open ? <button type="button">Confirm</button> : null}
      <button type="button">Elsewhere</button>
    </>
  );
}

describe("useFocusBack", () => {
  it("gives the focus back to its control when what closed took it along", () => {
    const { rerender } = render(<FocusBackHost open />);
    focus("Confirm");
    rerender(<FocusBackHost open={false} />);
    expect(screen.getByRole("button", { name: "Reset" })).toHaveFocus();
  });

  it("leaves a focus the person moved elsewhere where it is", () => {
    const { rerender } = render(<FocusBackHost open />);
    focus("Elsewhere");
    rerender(<FocusBackHost open={false} />);
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });
});

/** A view with a heading, a Stop that may go, and a dialog it opens from state. */
function RescueHost({ stop, dialog }: { stop: boolean; dialog: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useFocusRescue(root, heading);
  return (
    <>
      <div ref={root}>
        <h2 ref={heading} tabIndex={-1}>
          The discussion
        </h2>
        {stop ? <button type="button">Stop</button> : null}
        <button type="button">Approve outcome</button>
      </div>
      {dialog ? (
        <div role="dialog" aria-label="Approve">
          <button type="button">Approve</button>
        </div>
      ) : null}
      <button type="button">Elsewhere</button>
    </>
  );
}

describe("useFocusRescue", () => {
  it("gives the heading the focus when the control that had it leaves the view", () => {
    const { rerender } = render(<RescueHost stop dialog={false} />);
    focus("Stop");
    rerender(<RescueHost stop={false} dialog={false} />);
    expect(screen.getByRole("heading", { name: "The discussion" })).toHaveFocus();
  });

  it("gives the focus back to the control that opened a dialog once it closes", () => {
    const { rerender } = render(<RescueHost stop dialog={false} />);
    focus("Approve outcome");
    rerender(<RescueHost stop dialog />);
    focus("Approve");
    rerender(<RescueHost stop dialog={false} />);
    expect(screen.getByRole("button", { name: "Approve outcome" })).toHaveFocus();
  });

  it("leaves a focus the person moved out of the view alone", () => {
    const { rerender } = render(<RescueHost stop dialog={false} />);
    focus("Stop");
    focus("Elsewhere");
    rerender(<RescueHost stop={false} dialog={false} />);
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });
});

/** The dashboard's tiles over `boards`, and "Archive" for the board "Website". */
function BoardsHost({ boards, fetching }: { boards: Board[] | undefined; fetching: boolean }) {
  const follow = useFollowMovedBoard(boards, fetching, "boards-heading");
  return (
    <>
      <h2 id="boards-heading">Boards</h2>
      <ul>
        {(boards ?? []).map((entry) => (
          <li key={entry.id} data-board-id={entry.id}>
            <button type="button" aria-haspopup="menu">
              More actions for {entry.name}
            </button>
          </li>
        ))}
      </ul>
      <button type="button" onClick={() => follow({ boardId: "board-2", archived: true })}>
        Archive
      </button>
    </>
  );
}

describe("useFollowMovedBoard", () => {
  const website = board("board-2", "Website");
  const archived = { ...website, status: "archived" } as const satisfies Board;

  it("waits for the list to show the board in its new state, then focuses its tile's menu", async () => {
    const { rerender } = render(<BoardsHost boards={[website]} fetching={false} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Archive" }));
    rerender(<BoardsHost boards={[website]} fetching />);
    expect(screen.getByRole("button", { name: "Archive" })).toHaveFocus();
    rerender(<BoardsHost boards={[archived]} fetching={false} />);
    expect(screen.getByRole("button", { name: "More actions for Website" })).toHaveFocus();
  });

  it("goes to the heading when the board is no longer listed", async () => {
    const { rerender } = render(<BoardsHost boards={[website]} fetching={false} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Archive" }));
    rerender(<BoardsHost boards={[]} fetching />);
    expect(screen.getByRole("button", { name: "Archive" })).toHaveFocus();
    rerender(<BoardsHost boards={[]} fetching={false} />);
    expect(screen.getByRole("heading", { name: "Boards" })).toHaveFocus();
  });
});
