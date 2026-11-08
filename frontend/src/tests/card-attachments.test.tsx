import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TicketFiles } from "@/features/cards/TicketFiles";
import {
  attachmentErrorText,
  NETWORK_HINT,
  uploaderText,
} from "@/features/cards/useCardAttachments";
import { ApiError } from "@/lib/api";
import {
  ATTACHMENT_MAX_BYTES,
  attachmentRefusal,
  extensionOf,
  formatSize,
  uploadContentType,
} from "@/lib/api/attachmentRules";
import type { Attachment } from "@/lib/types";
import { ATTACHMENTS_PATH, attachment, attachmentHandlers } from "./msw/attachments";
import { CARD_ID, PERSON_ID } from "./msw/cards";
import { apiPath } from "./msw/envelope";
import { BOARD_ID } from "./msw/loops";
import { server } from "./msw/server";

const IMAGE = attachment({
  id: "att-2",
  original_filename: "diagram.png",
  content_type: "image/png",
  size_bytes: 3 * 1024 * 1024 + 300 * 1024,
});

async function renderSection(
  rows: Attachment[],
  { readOnly = false, currentActorId = "actor-me" } = {},
) {
  const files = attachmentHandlers(rows);
  server.use(...files.handlers);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TicketFiles
        boardId={BOARD_ID}
        cardId={CARD_ID}
        readOnly={readOnly}
        currentActorId={currentActorId}
      />
    </QueryClientProvider>,
  );
  const section = await screen.findByRole("region", { name: /^Files/ });
  await waitFor(() => expect(within(section).queryByText("Loading files…")).toBeNull());
  // applyAccept off: the picker's "All files" lets a person choose what `accept` leaves out.
  return { files, section, user: userEvent.setup({ applyAccept: false }) };
}

function chooser(section: HTMLElement): HTMLInputElement {
  const input = within(section).getByLabelText("Choose files to attach");
  if (!(input instanceof HTMLInputElement)) throw new Error("Expected the file input");
  return input;
}

const textFile = (name: string, text = "# Plan\n") => new File([text], name, { type: "" });

beforeEach(() => {
  document.cookie = "tralala_csrf=csrf-attach";
});

afterEach(() => {
  document.cookie = "tralala_csrf=; max-age=0";
});

describe("the rules the client checks before sending", () => {
  it("reads the extension as the server does and sizes in KB/MB with one decimal", () => {
    expect(extensionOf("Report.PDF")).toBe(".pdf");
    expect(extensionOf(".md")).toBe("");
    expect(extensionOf("archive.tar.gz")).toBe(".gz");
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(2560)).toBe("2.5 KB");
    expect(formatSize(ATTACHMENT_MAX_BYTES)).toBe("8.0 MB");
  });

  it("refuses an unknown extension, an empty file and one over the limit, with the reason", () => {
    expect(attachmentRefusal({ name: "run.exe", size: 10 })).toMatch(
      /^This type of file cannot be attached\. Allowed: \.docx .* \.gif\.$/,
    );
    expect(attachmentRefusal({ name: "empty.txt", size: 0 })).toBe("The file is empty.");
    expect(attachmentRefusal({ name: "big.pdf", size: ATTACHMENT_MAX_BYTES + 1 })).toBe(
      "The file is 8.0 MB; the limit is 8.0 MB per file.",
    );
    expect(attachmentRefusal({ name: "fine.pdf", size: ATTACHMENT_MAX_BYTES })).toBeNull();
  });

  it("declares the file's own type, or the allowlist's when the browser gives none", () => {
    expect(uploadContentType({ name: "a.png", type: "image/png" })).toBe("image/png");
    expect(uploadContentType({ name: "notes.md", type: "" })).toBe("text/markdown");
    expect(uploadContentType({ name: "odd", type: "" })).toBe("application/octet-stream");
  });

  it("words a read-only refusal, the server's own message and a network failure", () => {
    const readOnly = new ApiError("This Loop is read-only", {
      code: "loop_read_only",
      status: 409,
    });
    const refused = new ApiError("File content does not match its extension", {
      code: "validation_failed",
      status: 422,
    });
    expect(attachmentErrorText(readOnly)).toBe("This Ticket is read-only.");
    expect(attachmentErrorText(refused)).toBe("File content does not match its extension");
    expect(attachmentErrorText(new TypeError("Failed to fetch"))).toBe(NETWORK_HINT);
    expect(uploaderText(PERSON_ID, "actor-me")).toBe(PERSON_ID);
    expect(uploaderText("actor-me", "actor-me")).toBe("you");
  });
});

describe("the Files section of a Ticket", () => {
  it("says so when nothing is attached, with the count, Add file and the drop zone", async () => {
    const { section } = await renderSection([]);
    expect(within(section).getByText("No files yet")).toBeInTheDocument();
    expect(within(section).getByRole("heading", { name: /^Files\s*0$/ })).toBeInTheDocument();
    const zone = within(section).getByRole("button", {
      name: /Drop a file here, or use Add file\./,
    });
    expect(zone).toHaveTextContent(
      "Documents, presentations, spreadsheets, PDF, text, Markdown, JSON and images, up to 8 MB each.",
    );
    // Add file and a click on the drop zone open the same picker.
    let opened = 0;
    chooser(section).addEventListener("click", () => {
      opened += 1;
    });
    const user = userEvent.setup();
    await user.click(within(section).getByRole("button", { name: "Add file" }));
    await user.click(zone);
    expect(opened).toBe(2);
  });

  it("lists each file with its size, who uploaded it, a download link and a thumbnail for an image", async () => {
    const { section } = await renderSection([attachment(), IMAGE]);
    const list = within(section).getByRole("list", { name: "Attached files" });
    const [text, image] = within(list).getAllByRole("listitem");
    if (!text || !image) throw new Error("Expected two rows");
    expect(text).toHaveTextContent("notes.md");
    expect(text).toHaveTextContent(`2.5 KB · Uploaded by ${PERSON_ID}`);
    expect(within(text).queryByRole("img")).toBeNull();
    expect(within(text).getByRole("link", { name: "Download notes.md" })).toHaveAttribute(
      "href",
      apiPath(`${ATTACHMENTS_PATH}/att-1/download`),
    );
    expect(image).toHaveTextContent("3.3 MB");
    const open = within(image).getByRole("link", { name: "Open diagram.png in a new tab" });
    expect(open).toHaveAttribute("target", "_blank");
    expect(open.querySelector("img")).toHaveAttribute(
      "src",
      apiPath(`${ATTACHMENTS_PATH}/att-2/download`),
    );
  });

  it("uploads a file as the raw body with its type and name, and appends the row", async () => {
    const { files, section, user } = await renderSection([], { currentActorId: PERSON_ID });
    await user.upload(chooser(section), textFile("plan.md"));
    const list = await within(section).findByRole("list", { name: "Attached files" });
    expect(list).toHaveTextContent("plan.md");
    expect(list).toHaveTextContent("7 B · Uploaded by you");
    expect(within(section).getByRole("list", { name: "Uploads" })).toHaveTextContent(
      "plan.md: Uploaded",
    );
    expect(files.state.uploads).toEqual([
      {
        cardId: CARD_ID,
        filename: "plan.md",
        contentType: "text/markdown",
        csrf: "csrf-attach",
        body: "# Plan\n",
      },
    ]);
  });

  it("uploads several dropped files one after another, each with its own result", async () => {
    const { files, section } = await renderSection([]);
    fireEvent.drop(within(section).getByRole("button", { name: /Drop a file here/ }), {
      dataTransfer: {
        types: ["Files"],
        files: [textFile("one.txt", "1"), textFile("two.json", "{}"), textFile("three.txt", "3")],
      },
    });
    await waitFor(() => expect(files.state.uploads).toHaveLength(3));
    const list = await within(section).findByRole("list", { name: "Attached files" });
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(3));
    expect(files.state.uploads.map((upload) => upload.filename)).toEqual([
      "one.txt",
      "two.json",
      "three.txt",
    ]);
    expect(files.state.uploads[1]?.contentType).toBe("application/json");
  });

  it("stops a refused extension and an oversized file before sending, with the reason", async () => {
    const { files, section, user } = await renderSection([]);
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: ATTACHMENT_MAX_BYTES + 1 });
    await user.upload(chooser(section), [new File(["MZ"], "tool.exe"), big]);
    const uploads = within(section).getByRole("list", { name: "Uploads" });
    expect(uploads).toHaveTextContent("tool.exe: Not sent");
    expect(uploads).toHaveTextContent("This type of file cannot be attached.");
    expect(uploads).toHaveTextContent("big.pdf: Not sent");
    expect(uploads).toHaveTextContent("The file is 8.0 MB; the limit is 8.0 MB per file.");
    expect(files.state.uploads).toEqual([]);
    expect(within(section).getByText("No files yet")).toBeInTheDocument();
  });

  it("shows a refusal from the server in its words", async () => {
    const { files, section, user } = await renderSection([]);
    files.state.refuse = {
      status: 422,
      code: "validation_failed",
      message: "File content does not match its extension",
    };
    await user.upload(chooser(section), textFile("fake.txt"));
    const uploads = within(section).getByRole("list", { name: "Uploads" });
    await waitFor(() => expect(uploads).toHaveTextContent("fake.txt: Not uploaded"));
    expect(uploads).toHaveTextContent("File content does not match its extension");
    expect(within(section).getByText("No files yet")).toBeInTheDocument();
  });

  it("shows a network failure as a hint to try again", async () => {
    const { section, user } = await renderSection([]);
    server.use(http.post(apiPath(ATTACHMENTS_PATH), () => HttpResponse.error()));
    await user.upload(chooser(section), textFile("plan.md"));
    const uploads = within(section).getByRole("list", { name: "Uploads" });
    await waitFor(() => expect(uploads).toHaveTextContent(NETWORK_HINT));
  });

  it("asks once before deleting, sends DELETE and removes the row", async () => {
    const { files, section, user } = await renderSection([attachment(), IMAGE]);
    await user.click(within(section).getByRole("button", { name: "Delete notes.md" }));
    expect(within(section).getByText("Delete notes.md?")).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Keep" }));
    expect(within(section).queryByText("Delete notes.md?")).toBeNull();
    expect(files.state.deleted).toEqual([]);

    await user.click(within(section).getByRole("button", { name: "Delete notes.md" }));
    await user.click(within(section).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(within(section).queryByText("notes.md")).toBeNull());
    expect(files.state.deleted).toEqual(["att-1"]);
    expect(within(section).getByText("diagram.png")).toBeInTheDocument();
  });

  it("shows a 409 on delete as a read-only Ticket and keeps the row", async () => {
    const { files, section, user } = await renderSection([attachment()]);
    files.state.refuse = { status: 409, code: "loop_read_only", message: "This Loop is read-only" };
    await user.click(within(section).getByRole("button", { name: "Delete notes.md" }));
    await user.click(within(section).getByRole("button", { name: "Delete" }));
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "This Ticket is read-only.",
    );
    expect(within(section).getByText("notes.md")).toBeInTheDocument();
  });

  it("shows a read-only Ticket's files without a way to add or delete", async () => {
    const { section } = await renderSection([attachment(), IMAGE], { readOnly: true });
    expect(within(section).getAllByRole("listitem")).toHaveLength(2);
    expect(within(section).getByRole("link", { name: "Download notes.md" })).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: "Add file" })).toBeNull();
    expect(within(section).queryByLabelText("Choose files to attach")).toBeNull();
    expect(within(section).queryByRole("button", { name: /^Delete/ })).toBeNull();
    expect(within(section).queryByRole("button", { name: /Drop a file here/ })).toBeNull();
  });
});
