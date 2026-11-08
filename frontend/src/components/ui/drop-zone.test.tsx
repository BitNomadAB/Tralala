import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DropZone } from "./drop-zone";
import { carriesFiles } from "./useFileDrop";

function file(name: string): File {
  return new File(["content"], name, { type: "text/plain" });
}

function setup(props: { disabled?: boolean } = {}) {
  const onFiles = vi.fn();
  render(
    <DropZone
      hint="Drop a file here, or use Add file."
      detail="Text and images, up to 8 MB each."
      accept=".txt,.png"
      onFiles={onFiles}
      {...props}
    />,
  );
  return {
    onFiles,
    zone: screen.getByRole("button", { name: /Drop a file here/ }),
    picker: screen.getByLabelText("Choose files"),
  };
}

describe("DropZone", () => {
  it("hands its picker to a ref, so a button elsewhere opens the same input", () => {
    const ref: { current: HTMLInputElement | null } = { current: null };
    render(<DropZone hint="Drop here" onFiles={() => undefined} inputRef={ref} />);
    expect(ref.current).toBe(screen.getByLabelText("Choose files"));
  });

  it("calls onFiles with the files of a drop", () => {
    const { onFiles, zone } = setup();
    const dropped = [file("a.txt"), file("b.txt")];
    fireEvent.drop(zone, { dataTransfer: { files: dropped, types: ["Files"] } });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith(dropped);
  });

  it("marks a drag that carries files and leaves a text drag alone", () => {
    const { zone } = setup();
    fireEvent.dragEnter(zone, { dataTransfer: { types: ["text/plain"] } });
    expect(zone).not.toHaveAttribute("data-dragging");

    fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"] } });
    expect(zone).toHaveAttribute("data-dragging", "true");
    expect(zone).toHaveTextContent("Drop the files here.");
    fireEvent.dragOver(zone, { dataTransfer: { types: ["Files"], dropEffect: "none" } });

    fireEvent.dragLeave(zone, { relatedTarget: document.body });
    expect(zone).not.toHaveAttribute("data-dragging");
    expect(zone).toHaveTextContent("Drop a file here, or use Add file.");
  });

  it("ignores a drop without files", () => {
    const { onFiles, zone } = setup();
    fireEvent.drop(zone, { dataTransfer: { files: [], types: ["Files"] } });
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("calls onFiles with a picked file and clears the picker for the next choice", async () => {
    const user = userEvent.setup();
    const { onFiles, picker } = setup();
    expect(picker).toHaveAttribute("accept", ".txt,.png");
    const picked = file("notes.txt");
    await user.upload(picker, picked);
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith([picked]);
    expect(picker).toHaveValue("");
  });

  it("opens the picker on a click and on Enter", async () => {
    const user = userEvent.setup();
    const { zone, picker } = setup();
    const click = vi.spyOn(picker, "click");
    await user.click(zone);
    expect(click).toHaveBeenCalledTimes(1);
    zone.focus();
    await user.keyboard("{Enter}");
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("takes nothing while disabled", () => {
    const { onFiles, zone, picker } = setup({ disabled: true });
    expect(zone).toBeDisabled();
    expect(picker).toBeDisabled();
    fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"] } });
    fireEvent.drop(zone, { dataTransfer: { files: [file("a.txt")], types: ["Files"] } });
    expect(zone).not.toHaveAttribute("data-dragging");
    expect(onFiles).not.toHaveBeenCalled();
  });
});

describe("carriesFiles", () => {
  it("is true only for a drag that carries files", () => {
    expect(carriesFiles(["text/plain", "Files"])).toBe(true);
    expect(carriesFiles(["text/uri-list"])).toBe(false);
    expect(carriesFiles([])).toBe(false);
  });
});
