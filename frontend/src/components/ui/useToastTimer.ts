import { useEffect, useRef, useState, type FocusEvent } from "react";

/**
 * Calls `onExpire` once `duration` milliseconds have run while nobody holds the toast: while the
 * pointer is on it or focus is in it, the time stands still and what is left is kept, so a toast
 * being read or reached with Tab gets the rest of its time afterwards (WCAG 2.2.1). A `null`
 * duration never expires. Spread `handlers` on the toast.
 */
export function useToastTimer(duration: number | null, onExpire: () => void) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;
  const remaining = useRef(duration);

  useEffect(() => {
    const left = remaining.current;
    if (paused || left === null) return undefined;
    const started = Date.now();
    const timer = window.setTimeout(onExpire, left);
    return () => {
      window.clearTimeout(timer);
      remaining.current = Math.max(0, left - (Date.now() - started));
    };
  }, [paused, onExpire]);

  const handlers = {
    onPointerEnter: () => {
      setHovered(true);
    },
    onPointerLeave: () => {
      setHovered(false);
    },
    onFocus: () => {
      setFocused(true);
    },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
    },
  };
  return { paused, handlers };
}
