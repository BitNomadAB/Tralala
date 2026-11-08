import { EmptyState } from "@/components/ui/empty-state";
import { Section } from "@/components/ui/section";
import { describeError } from "@/lib/describeError";
import { useDiscussionInbox } from "@/lib/queries";
import type { DiscussionInboxRow } from "@/lib/types";
import { DiscussionRows, type DiscussionRowItem } from "./DiscussionRows";
import { INBOX_GROUPS, inboxAside, inboxMark, inboxMeta, inboxPath } from "./inboxRules";

type InboxItem = DiscussionRowItem & { row: DiscussionInboxRow };

function item(row: DiscussionInboxRow): InboxItem {
  return {
    id: `${row.board_id}/${row.discussion_id}`,
    mark: inboxMark(row),
    question: row.question,
    aside: inboxAside(row),
    meta: inboxMeta(row),
    row,
  };
}

/**
 * The Discussions page is an inbox across every board the person may read: what waits for their
 * decision, where the agents are talking, and what was decided. A row opens the discussion as a
 * page of its Ticket. The inbox refetches every 30 s while visible and when a discussion's events
 * arrive; a discussion starts from a Ticket, never from here.
 */
export function DiscussionsPage() {
  const inbox = useDiscussionInbox();
  const rows = inbox.data?.items ?? [];
  const total = inbox.data?.total ?? 0;

  return (
    <section className="mx-auto flex w-full max-w-[980px] flex-col gap-8">
      <div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Discussions</h1>
        <p className="mt-1.5 text-[15px] text-[var(--muted-foreground)]">
          Where the agents advise. You decide. A discussion starts from a Ticket: open one and
          choose Ask the agents.
        </p>
      </div>

      {inbox.isLoading ? (
        <p className="m-0 text-sm text-[var(--muted-foreground)]">Reading your discussions…</p>
      ) : inbox.error ? (
        <p role="alert" className="m-0 text-sm text-[var(--destructive)]">
          {describeError(inbox.error, "Could not read the discussions.")}
        </p>
      ) : rows.length === 0 ? (
        <EmptyState
          className="card-surface px-4 py-3.5"
          message="No discussions yet."
          detail="When you ask the agents about a Ticket, the discussion shows up here."
        />
      ) : (
        <>
          {INBOX_GROUPS.map((group) => {
            const items = rows.filter((row) => row.waits_for === group.waitsFor).map(item);
            return (
              <Section key={group.waitsFor} title={group.title} count={items.length}>
                {items.length === 0 ? (
                  <EmptyState message={group.empty} />
                ) : (
                  <DiscussionRows
                    rows={items}
                    label={group.title}
                    hrefFor={(entry) => inboxPath(entry.row)}
                  />
                )}
              </Section>
            );
          })}
          {total > rows.length ? (
            <p className="m-0 text-xs text-[var(--foreground-faint)]">
              {rows.length} of {total} discussions are listed.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
