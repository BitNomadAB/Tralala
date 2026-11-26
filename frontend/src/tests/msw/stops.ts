import type { StopList } from "@/lib/types";

/** The list a Loop has while no person has written one (`loop_stops.DEFAULT_STOPS`). */
export const DEFAULT_STOP_LIST: StopList = {
  stops: [
    "Deployment to production",
    "Deleting data",
    "Money",
    "Something sent to people outside",
    "A new kind of personal data",
  ],
  is_default: true,
};
