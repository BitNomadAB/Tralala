import { useRef } from "react";
import { HeldButton } from "@/components/ui/held-button";
import { Section } from "@/components/ui/section";
import { useAnnounceWhen } from "@/components/ui/useAnnounce";
import { useAuth } from "@/features/auth/useAuth";
import type { Loop } from "@/lib/types";
import { LoopDocumentsPanel } from "./LoopDocumentsPanel";
import type { PlanTab } from "./loopUi";
import { DOCUMENTS_CHANGED_TEXT, useDocumentsBehind } from "./useDocumentsBehind";
import { useFocusBack } from "./useFocusBack";

/**
 * The Plan tab: the planning documents with their generation, candidates and review. The plan's
 * Tickets live on the Kanban, and the Loop's header names what holds a Phase up. `doc` is the
 * open document (`?doc=`).
 *
 * The documents are not replaced while the person has them on screen: when someone else handed in
 * a new revision, a line says so and "Show the latest" reads it. Once it is read the line goes,
 * and a focus it took along moves to the open document's switch (WCAG 2.4.3).
 */
export function LoopPlanTab({
  boardId,
  loop,
  doc,
  onDocChange,
  readOnly,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  doc: PlanTab;
  onDocChange: (doc: PlanTab) => void;
  readOnly: boolean;
  onChanged: () => void;
}) {
  const { actor } = useAuth();
  const tab = useRef<HTMLDivElement>(null);
  const latest = useDocumentsBehind(boardId, loop.id, onChanged);
  useAnnounceWhen(latest.behind, DOCUMENTS_CHANGED_TEXT);
  useFocusBack(latest.behind, () =>
    tab.current?.querySelector<HTMLElement>('[aria-pressed="true"]'),
  );
  return (
    <div ref={tab} className="flex flex-col gap-10">
      <Section title="Planning documents" size="lg" level={2}>
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          Info is written by a person. Analysis and RoadMap pair a technical view with a
          plain-language one.
        </p>
        {latest.behind ? (
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--warning)] p-2 text-xs text-[var(--warning)]">
            <span>{DOCUMENTS_CHANGED_TEXT}</span>
            <HeldButton size="sm" variant="outline" held={latest.loading} onClick={onChanged}>
              Show the latest
            </HeldButton>
          </div>
        ) : null}
        <LoopDocumentsPanel
          boardId={boardId}
          loop={loop}
          tab={doc}
          onTabChange={onDocChange}
          isHuman={actor?.type === "user"}
          readOnly={readOnly}
          onChanged={onChanged}
        />
      </Section>
    </div>
  );
}
