import type { Politeness } from "@/components/ui/useAnnounce";

/** The announcer's live region for `politeness`, which `useAnnounce` writes to. */
export function announcer(politeness: Politeness = "polite"): HTMLElement {
  const region = document.querySelector<HTMLElement>(`[data-announcer="${politeness}"]`);
  if (!region) throw new Error(`The ${politeness} announcer region is not in the page`);
  return region;
}
