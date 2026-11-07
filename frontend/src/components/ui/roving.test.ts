import { describe, expect, it } from "vitest";
import { idPart, rovingIndex, tabIds } from "./roving";

describe("rovingIndex", () => {
  it("wraps a horizontal set at both ends with Left and Right", () => {
    expect(rovingIndex("ArrowRight", 0, 3, "horizontal")).toBe(1);
    expect(rovingIndex("ArrowRight", 2, 3, "horizontal")).toBe(0);
    expect(rovingIndex("ArrowLeft", 0, 3, "horizontal")).toBe(2);
    expect(rovingIndex("ArrowDown", 0, 3, "horizontal")).toBeNull();
  });

  it("stops a vertical set at its ends with Up and Down", () => {
    expect(rovingIndex("ArrowDown", 0, 3, "vertical")).toBe(1);
    expect(rovingIndex("ArrowDown", 2, 3, "vertical")).toBe(2);
    expect(rovingIndex("ArrowUp", 0, 3, "vertical")).toBe(0);
    expect(rovingIndex("ArrowRight", 0, 3, "vertical")).toBeNull();
  });

  it("goes to the first on Home and the last on End, and nowhere in an empty set", () => {
    expect(rovingIndex("Home", 2, 3, "horizontal")).toBe(0);
    expect(rovingIndex("End", 0, 3, "vertical")).toBe(2);
    expect(rovingIndex("Enter", 1, 3, "horizontal")).toBeNull();
    expect(rovingIndex("Home", 0, 0, "horizontal")).toBeNull();
  });
});

describe("tabIds", () => {
  it("pairs a tab with its panel under one base, with the value made safe for an id", () => {
    expect(idPart("needs input/now")).toBe("needs_input_now");
    expect(tabIds("act", "In Progress")).toEqual({
      tab: "act-tab-In_Progress",
      panel: "act-panel-In_Progress",
    });
  });
});
