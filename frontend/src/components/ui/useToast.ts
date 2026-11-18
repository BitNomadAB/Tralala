import { createContext, useContext } from "react";

export type ToastVariant = "info" | "success" | "warning" | "error";

/** A button on the toast besides Dismiss, such as "Undo"; pressing it also closes the toast. */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

/** What a caller passes; an undefined description is the same as none. */
export interface ToastInput {
  title: string;
  description?: string | undefined;
  variant?: ToastVariant;
  action?: ToastAction | undefined;
}

/** A toast on screen: what was pushed, with the id it is dismissed by. */
export interface Toast {
  id: number;
  title: string;
  description: string | undefined;
  variant: ToastVariant;
  action: ToastAction | undefined;
}

export interface ToastContextValue {
  push: (toast: ToastInput) => void;
}

/**
 * How long a toast that is not an error stays, counted only while nobody points at it or has
 * focus in it (WCAG 2.2.1). An error has no timer: it stays until it is dismissed (WCAG 3.3.1).
 */
export const TOAST_DURATION_MS = 5000;

/**
 * At most this many toasts show at once. An error and a toast with an action stay until they are
 * used or dismissed, and inside a modal dialog the focus trap keeps a keyboard user from their
 * Dismiss, so without a cap they would pile up over the page.
 */
export const MAX_TOASTS = 3;

/** Whether a toast leaves by itself: neither an error nor one with an action (`ToastItem`). */
export function toastExpires(toast: Toast): boolean {
  return toast.variant !== "error" && toast.action === undefined;
}

/** The same message: variant, title and description. A toast with an action is its own change. */
function sameToast(a: Toast, b: Toast): boolean {
  return (
    a.action === undefined &&
    b.action === undefined &&
    a.variant === b.variant &&
    a.title === b.title &&
    a.description === b.description
  );
}

/**
 * The toasts shown once `toast` is added to `current`: the same message shown already gives way to
 * it, so it is read once more instead of stacking; past `MAX_TOASTS` the oldest toast that leaves
 * by itself makes room first, else the oldest one. The new toast always shows.
 */
export function withToast(current: readonly Toast[], toast: Toast): Toast[] {
  const older = current.filter((shown) => !sameToast(shown, toast));
  while (older.length >= MAX_TOASTS) {
    const timed = older.findIndex(toastExpires);
    older.splice(timed >= 0 ? timed : 0, 1);
  }
  return [...older, toast];
}

/** Shared by `ToastProvider` (toast.tsx) and `useToast`; a component file exports only components. */
export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
