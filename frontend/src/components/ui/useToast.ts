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

/** Shared by `ToastProvider` (toast.tsx) and `useToast`; a component file exports only components. */
export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
