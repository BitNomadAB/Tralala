import { useLocation } from "react-router-dom";

/** Where the memory router is, so a test can see a navigation: the path, and the query apart. */
export function LocationProbe() {
  const location = useLocation();
  return (
    <>
      <output aria-label="Location">{location.pathname}</output>
      <output aria-label="Query">{location.search}</output>
    </>
  );
}
