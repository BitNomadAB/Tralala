import { useLocation } from "react-router-dom";

/** Where the memory router is, so a test can see a navigation. */
export function LocationProbe() {
  const location = useLocation();
  return <output aria-label="Location">{location.pathname}</output>;
}
