import { Section } from "@/components/ui/section";
import { useAuth } from "@/features/auth/useAuth";
import type { Loop } from "@/lib/types";
import { LoopDocumentsPanel } from "./LoopDocumentsPanel";
import type { PlanTab } from "./loopUi";
import { PlanReadiness } from "./PlanReadiness";

/**
 * The Plan tab: the planning documents with their generation, candidates and review, then the
 * published Phases with their readiness. `doc` is the open document (`?doc=`).
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
  return (
    <div className="flex flex-col gap-10">
      <Section title="Planning documents" size="lg" level={2}>
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          Info is written by a person. Analysis and RoadMap pair a technical view with a
          plain-language one.
        </p>
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
      <Section title="Phases and readiness" size="lg" level={2}>
        <p className="mb-3 text-sm text-[var(--muted-foreground)]">
          Phases group the work; columns do not. Readiness comes from the approved dependency graph.
        </p>
        <PlanReadiness boardId={boardId} loop={loop} onChanged={onChanged} />
      </Section>
    </div>
  );
}
