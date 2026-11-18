import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { ConfirmDialog, type Confirmation } from "@/features/settings/ConfirmDialog";
import { copyText } from "@/features/settings/copyText";
import { OneTimeSecretDialog } from "@/features/settings/OneTimeSecretDialog";
import { useOneTimeSecret } from "@/features/settings/useOneTimeSecret";

const QUESTION: Confirmation = {
  title: "Remove the repository?",
  consequence: "Boards that use it lose it. The repository itself is not touched.",
  confirmLabel: "Remove repository",
};

/** "Remove" asks; the dialog stays while `busy` says the removal runs. */
function ConfirmHost({ busy, onConfirm }: { busy: string | null; onConfirm: () => void }) {
  const [question, setQuestion] = useState<Confirmation | null>(null);
  return (
    <>
      <button type="button" onClick={() => setQuestion(QUESTION)}>
        Remove
      </button>
      <ConfirmDialog
        question={question}
        busy={busy}
        onConfirm={onConfirm}
        onCancel={() => setQuestion(null)}
      />
    </>
  );
}

describe("the question before an action that cannot be undone", () => {
  it("asks, says what happens, and starts on Cancel so a stray Enter changes nothing", async () => {
    const onConfirm = vi.fn<() => void>();
    const user = userEvent.setup();
    render(<ConfirmHost busy={null} onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "Remove" }));

    const dialog = screen.getByRole("dialog", { name: QUESTION.title });
    expect(dialog).toHaveAccessibleDescription(QUESTION.consequence);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Remove repository" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("holds the action with what it waits for while it runs", async () => {
    const onConfirm = vi.fn<() => void>();
    const user = userEvent.setup();
    render(<ConfirmHost busy="Removing…" onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "Remove" }));
    const confirm = screen.getByRole("button", { name: "Remove repository" });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAccessibleDescription("Removing…");
    await user.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("copying a text", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("copies it and says so", async () => {
    userEvent.setup();
    expect(await copyText("trl_secret")).toBe(true);
    expect(await navigator.clipboard.readText()).toBe("trl_secret");
  });

  it("says it did not copy when the browser refuses the write", async () => {
    userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("not allowed"));
    expect(await copyText("trl_secret")).toBe(false);
  });

  it("says it did not copy where the browser has no clipboard (plain HTTP)", async () => {
    vi.stubGlobal("navigator", {});
    expect(await copyText("trl_secret")).toBe(false);
  });
});

describe("the state of a secret shown once", () => {
  it("asks before closing an uncopied secret, closes a copied one, and starts over for a new one", () => {
    const onClose = vi.fn<() => void>();
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) =>
        useOneTimeSecret({ value, noun: "token", fieldId: "secret", onClose }),
      { initialProps: { value: "trl_first" }, wrapper: ToastProvider },
    );
    act(() => result.current.requestClose());
    expect(result.current.asking).toBe(true);
    // Asked already, the same gesture keeps it open.
    act(() => result.current.requestClose());
    expect(result.current.asking).toBe(false);
    expect(onClose).not.toHaveBeenCalled();

    act(() => result.current.markCopied());
    expect(result.current.copied).toBe(true);
    rerender({ value: "trl_second" });
    expect(result.current.copied).toBe(false);
    act(() => result.current.requestClose());
    expect(result.current.asking).toBe(true);
    act(() => result.current.markCopied());
    act(() => result.current.requestClose());
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

/** A token dialog opened from another dialog, which is gone when it closes. */
function SecretHost() {
  const [value, setValue] = useState<string | null>("trl_issued");
  return (
    <>
      <button type="button" id="new-access">
        New access
      </button>
      <OneTimeSecretDialog
        value={value}
        title="Copy this token now"
        description="It is shown once."
        label="New API token"
        noun="token"
        returnFocusId="new-access"
        onClose={() => setValue(null)}
      />
    </>
  );
}

describe("the dialog that shows a secret once", () => {
  it("gives the focus to the named control on closing, as what opened it has gone", async () => {
    render(
      <ToastProvider>
        <SecretHost />
      </ToastProvider>,
    );
    fireEvent.copy(screen.getByLabelText("New API token"));
    await userEvent.setup().click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "New access" })).toHaveFocus();
  });
});
