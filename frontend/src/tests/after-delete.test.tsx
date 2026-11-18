import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { afterDeletedRow, rowIndex, rowOf, rowsOf } from "@/features/cards/afterDelete";

/** Rows of notes; each of `editable` has an Edit button marked as the row's focus target. */
function renderRows(ids: string[], editable: string[] = ids) {
  render(
    <>
      <h3 tabIndex={-1}>Your notes</h3>
      <ul aria-label="Notes">
        {ids.map((id) => (
          <li key={id} data-note-id={id}>
            Note {id}
            {editable.includes(id) ? (
              <button type="button" data-focus-target="edit-note">
                Edit {id}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </>,
  );
  return screen.getByRole("list", { name: "Notes" });
}

const heading = () => screen.getByRole("heading", { name: "Your notes" });
const edit = (id: string) => screen.getByRole("button", { name: `Edit ${id}` });
const after = (root: Element, id: string, index: number) =>
  afterDeletedRow(root, { attribute: "note-id", id, target: "edit-note", index }, heading);

describe("the rows of a list", () => {
  it("are found in order, one by its id, and where one stands", () => {
    const root = renderRows(["a", "b", "c"]);
    expect(rowsOf(root, "note-id").map((row) => row.dataset.noteId)).toEqual(["a", "b", "c"]);
    expect(rowOf(root, "note-id", "b")).toHaveTextContent("Note b");
    expect(rowOf(root, "note-id", "x")).toBeUndefined();
    expect(rowIndex(root, "note-id", "c")).toBe(2);
    expect(rowIndex(root, "note-id", "x")).toBe(-1);
    expect(rowsOf(null, "note-id")).toEqual([]);
  });
});

describe("the focus after a row was deleted", () => {
  it("goes to the row that took its place once it has left the list", () => {
    // "c" stood third; the list without it is a, b, d.
    const root = renderRows(["a", "b", "d"]);
    expect(after(root, "c", 2)).toBe(edit("d"));
  });

  it("goes to the next row while the deleted one is still shown, skipping it", () => {
    const root = renderRows(["a", "b", "c", "d"]);
    expect(after(root, "c", 2)).toBe(edit("d"));
  });

  it("goes to the row before when the last one was deleted", () => {
    expect(after(renderRows(["a", "b", "c"]), "d", 3)).toBe(edit("c"));
  });

  it("passes over rows without the control, then falls back to the heading", () => {
    const root = renderRows(["a", "b", "d"], ["a"]);
    expect(after(root, "c", 2)).toBe(edit("a"));
  });

  it("falls back to the heading when no row is left", () => {
    expect(after(renderRows([]), "a", 0)).toBe(heading());
  });
});
