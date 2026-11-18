import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { AnnouncerProvider } from "@/components/ui/announcer";
import { CommentComposer } from "@/features/cards/CommentComposer";
import type { AgentDirectoryEntry } from "@/lib/types";

const BRAVO: AgentDirectoryEntry = {
  id: "agent-bravo",
  name: "Bravo",
  role_template_id: null,
  role_template_name: null,
  role_template_scope: "board",
};

/** The composer over `comment`, with the suggestions `suggestions` open. */
function renderComposer(comment: string, suggestions: AgentDirectoryEntry[] = []) {
  const onSubmitComment = vi.fn<(content: string) => void>();
  const onCloseSuggestions = vi.fn<() => void>();
  render(
    <AnnouncerProvider>
      <CommentComposer
        comment={comment}
        onCommentChange={() => undefined}
        onCloseSuggestions={onCloseSuggestions}
        suggestions={suggestions}
        mentionIndex={0}
        onMentionIndexChange={() => undefined}
        onChooseAgent={() => undefined}
        commentField={createRef<HTMLTextAreaElement>()}
        onSubmitComment={onSubmitComment}
      />
    </AnnouncerProvider>,
  );
  return { field: screen.getByLabelText("New comment"), onSubmitComment, onCloseSuggestions };
}

describe("the comment box", () => {
  it("sends the comment without its outer spaces by Ctrl+Enter, Cmd+Enter or Send", () => {
    const { field, onSubmitComment } = renderComposer("  Looks good  ");
    fireEvent.keyDown(field, { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(field, { key: "Enter", metaKey: true });
    fireEvent.click(screen.getByRole("button", { name: "Send comment" }));
    expect(onSubmitComment.mock.calls).toEqual([["Looks good"], ["Looks good"], ["Looks good"]]);
    expect(screen.getByText("sends", { exact: false })).toHaveTextContent("Ctrl + Enter sends");
  });

  it("sends nothing for a blank comment", () => {
    const { field, onSubmitComment } = renderComposer("   ");
    expect(screen.getByRole("button", { name: "Send comment" })).toBeDisabled();
    fireEvent.keyDown(field, { key: "Enter", ctrlKey: true });
    expect(onSubmitComment).not.toHaveBeenCalled();
  });

  it("leaves plain Enter to the field, a new line", () => {
    const { field, onSubmitComment } = renderComposer("A first line");
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSubmitComment).not.toHaveBeenCalled();
  });

  it("closes the suggestions once the field loses the focus", () => {
    const { field, onCloseSuggestions } = renderComposer("@Br", [BRAVO]);
    expect(screen.getByRole("listbox", { name: "Mention an agent" })).toBeInTheDocument();
    fireEvent.blur(field);
    expect(onCloseSuggestions).toHaveBeenCalled();
  });
});
