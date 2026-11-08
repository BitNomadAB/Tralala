import { Fragment, type ReactElement, type ReactNode } from "react";

/** A crumb that leads somewhere: muted, underlined on hover. */
export const CRUMB_LINK =
  "text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline";

/**
 * The line over a page that can be sent as a URL: the crumbs (each a keyed element, the last one
 * marked `aria-current="page"` by its caller) with a faint slash between them, and `trailing` on
 * the right ("Back to the board").
 */
export function Breadcrumb({
  crumbs,
  trailing,
}: {
  crumbs: readonly ReactElement[];
  trailing?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3.5 border-b border-[var(--border-soft)] pb-2.5 text-[13px] text-[var(--muted-foreground)]">
      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-wrap items-center gap-2">
        {crumbs.map((crumb, index) => (
          <Fragment key={crumb.key ?? index}>
            {index > 0 ? (
              <span aria-hidden="true" className="text-[var(--foreground-faint)]">
                /
              </span>
            ) : null}
            {crumb}
          </Fragment>
        ))}
      </nav>
      {trailing === undefined ? null : (
        <>
          <span className="flex-1" />
          {trailing}
        </>
      )}
    </div>
  );
}
