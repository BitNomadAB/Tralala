import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import {
  confirmationProblem,
  fieldProblems,
  passwordProblem,
  problemAt,
} from "@/lib/fieldProblems";

describe("Field", () => {
  it("describes its control by the hint", () => {
    render(
      <Field label="Name" htmlFor="name" hint="Shown on the board.">
        <Input id="name" />
      </Field>,
    );

    const input = screen.getByLabelText("Name");
    expect(input).toHaveAccessibleDescription("Shown on the board.");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("marks its control invalid and describes it by the error first, then the hint", () => {
    render(
      <Field label="Name" htmlFor="name" hint="Shown on the board." error="Enter a name.">
        <Input id="name" />
      </Field>,
    );

    const input = screen.getByLabelText("Name");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Error: Enter a name. Shown on the board.");
    // Not by colour alone: the error carries an icon and the word, both outside the colour.
    const message = screen.getByText("Enter a name.").closest("p");
    expect(message?.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(message).toHaveTextContent("Error: Enter a name.");
  });

  it("gives a select and a textarea the same description", () => {
    render(
      <>
        <Field label="Role" htmlFor="role" error="Choose a role.">
          <Select id="role">
            <option>member</option>
          </Select>
        </Field>
        <Field label="Notes" htmlFor="notes" hint="Plain text.">
          <Textarea id="notes" />
        </Field>
      </>,
    );

    expect(screen.getByLabelText("Role")).toHaveAccessibleDescription("Error: Choose a role.");
    expect(screen.getByLabelText("Role")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Notes")).toHaveAccessibleDescription("Plain text.");
  });

  it("describes only the control its label names, and keeps a control's own description", () => {
    render(
      <>
        <p id="own">Typed by hand.</p>
        <Field label="Name" htmlFor="name" hint="Shown on the board." error="Enter a name.">
          <Input id="name" aria-describedby="own" />
          <Input id="other" aria-label="Other" />
        </Field>
      </>,
    );

    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "Typed by hand. Error: Enter a name. Shown on the board.",
    );
    const other = screen.getByLabelText("Other");
    expect(other).not.toHaveAttribute("aria-describedby");
    expect(other).not.toHaveAttribute("aria-invalid");
  });

  it("leaves a control without hint or error undescribed", () => {
    render(
      <Field label="Name" htmlFor="name" error="">
        <Input id="name" />
      </Field>,
    );

    const input = screen.getByLabelText("Name");
    expect(input).not.toHaveAttribute("aria-describedby");
    expect(input).not.toHaveAttribute("aria-invalid");
  });
});

describe("the field problems", () => {
  it("asks for eight characters and for the same password twice", () => {
    expect(passwordProblem("short")).toBe("Use at least 8 characters.");
    expect(passwordProblem("long-enough")).toBeNull();
    expect(confirmationProblem("long-enough", "")).toBe("Repeat the password.");
    expect(confirmationProblem("long-enough", "long-enougH")).toBe(
      "The two passwords do not match.",
    );
    expect(confirmationProblem("long-enough", "long-enough")).toBeNull();
  });

  it("makes a problem only of a message", () => {
    expect(problemAt("name", null)).toEqual([]);
    expect(problemAt("name", "Enter a name.")).toEqual([{ id: "name", message: "Enter a name." }]);
  });

  it("puts the fields a refusal names on their controls, in the form's order", () => {
    const refusal = new ApiError("Validation failed", {
      code: "validation_failed",
      status: 422,
      details: [
        { loc: ["body", "expires_in_days"], msg: "Must be at most 3650" },
        { loc: ["body", "name"], msg: "Must not be empty" },
        { loc: ["body", "unknown"], msg: "Not on this form" },
      ],
    });

    expect(
      fieldProblems(refusal, {
        name: "credential-name",
        expires_in_days: "credential-expiry",
      }),
    ).toEqual([
      { id: "credential-name", message: "Must not be empty" },
      { id: "credential-expiry", message: "Must be at most 3650" },
    ]);
    expect(fieldProblems(new Error("offline"), { name: "credential-name" })).toEqual([]);
  });
});
