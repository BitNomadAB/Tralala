import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { TicketFiles } from "@/features/cards/TicketFiles";
import { uploadAnnouncement } from "@/features/cards/useCardAttachments";
import type { Attachment } from "@/lib/types";
import { announcer } from "./announcer";
import { attachment, attachmentHandlers } from "./msw/attachments";
import { CARD_ID } from "./msw/cards";
import { BOARD_ID } from "./msw/loops";
import { server } from "./msw/server";

const SECOND = attachment({
  id: "att-2",
  original_filename: "plan.pdf",
  content_type: "application/pdf",
});

async function renderFiles(rows: Attachment[]) {
  const files = attachmentHandlers(rows);
  server.use(...files.handlers);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <TicketFiles boardId={BOARD_ID} cardId={CARD_ID} readOnly={false} currentActorId="me" />
      </ToastProvider>
    </QueryClientProvider>,
  );
  const section = await screen.findByRole("region", { name: /^Files/ });
  await waitFor(() => expect(within(section).queryByText("Loading files…")).toBeNull());
  return { files, section, user: userEvent.setup({ applyAccept: false }) };
}

describe("the focus around a file's delete", () => {
  it("asks with the focus on Keep, and Keep gives it back to the file's delete button", async () => {
    const { section, user } = await renderFiles([attachment()]);
    await user.click(within(section).getByRole("button", { name: "Delete notes.md" }));
    expect(within(section).getByRole("button", { name: "Keep" })).toHaveFocus();
    await user.click(within(section).getByRole("button", { name: "Keep" }));
    await waitFor(() =>
      expect(within(section).getByRole("button", { name: "Delete notes.md" })).toHaveFocus(),
    );
  });

  it("hands the focus to the next file after a delete, then to the Files heading, and says so", async () => {
    const { section, user } = await renderFiles([attachment(), SECOND]);
    await user.click(within(section).getByRole("button", { name: "Delete notes.md" }));
    await user.click(within(section).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(within(section).getByRole("button", { name: "Delete plan.pdf" })).toHaveFocus(),
    );
    await waitFor(() => expect(announcer()).toHaveTextContent("notes.md deleted"));
    await user.click(within(section).getByRole("button", { name: "Delete plan.pdf" }));
    await user.click(within(section).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(within(section).getByRole("heading", { name: /^Files/ })).toHaveFocus(),
    );
  });

  it("gives the focus back to the file's delete button when the delete is refused", async () => {
    const { files, section, user } = await renderFiles([attachment()]);
    files.state.refuse = { status: 409, code: "loop_read_only", message: "This Loop is read-only" };
    await user.click(within(section).getByRole("button", { name: "Delete notes.md" }));
    await user.click(within(section).getByRole("button", { name: "Delete" }));
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "This Ticket is read-only.",
    );
    await waitFor(() =>
      expect(within(section).getByRole("button", { name: "Delete notes.md" })).toHaveFocus(),
    );
  });
});

describe("the uploads' results", () => {
  it("are announced as each comes, a refused file at once", async () => {
    const { section, user } = await renderFiles([]);
    const picker = within(section).getByLabelText("Choose files to attach");
    await user.upload(picker, [new File(["MZ"], "tool.exe"), new File(["# Plan\n"], "plan.md")]);
    await waitFor(() => expect(announcer()).toHaveTextContent("plan.md: uploaded"));
    expect(within(section).getByRole("list", { name: "Uploads" })).not.toHaveAttribute("aria-live");
  });

  it("word each result: uploaded, or the reason", () => {
    expect(uploadAnnouncement({ name: "a.md", status: "uploaded", message: null })).toBe(
      "a.md: uploaded",
    );
    expect(
      uploadAnnouncement({ name: "b.md", status: "failed", message: "The file is empty." }),
    ).toBe("b.md: The file is empty.");
  });
});
