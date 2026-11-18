import { createContext, useContext, type AriaAttributes } from "react";

/** What a `Field` tells the control its label names: where its hint and error are, if any. */
export interface FieldControl {
  /** The id the Field's label points at; only the control with this id takes the rest. */
  controlId: string;
  /** The ids of the error and the hint the Field shows, space-separated, or undefined for none. */
  describedBy: string | undefined;
  invalid: boolean;
}

export const FieldContext = createContext<FieldControl | null>(null);

type ControlAria = Pick<AriaAttributes, "aria-describedby" | "aria-invalid">;

/**
 * The `aria-describedby` and `aria-invalid` a control renders: its own, plus the hint and error of
 * the Field around it. Only the control the Field's label names takes them, so a second input or a
 * button inside the same Field is not described by text that is not about it. `Input`, `Select`
 * and `Textarea` call this; a custom control inside a Field can too.
 */
export function useFieldControl(props: ControlAria & { id?: string | undefined }): ControlAria {
  const field = useContext(FieldContext);
  const own = props["aria-describedby"];
  if (!field || props.id !== field.controlId) {
    return { "aria-describedby": own, "aria-invalid": props["aria-invalid"] };
  }
  const describedBy = [own, field.describedBy].filter((id) => id !== undefined).join(" ");
  return {
    "aria-describedby": describedBy || undefined,
    "aria-invalid": field.invalid ? true : props["aria-invalid"],
  };
}
