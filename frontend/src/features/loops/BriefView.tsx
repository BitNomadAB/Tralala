import { useId, useState } from "react";
import { Segmented, SegmentedPanel } from "@/components/ui/segmented";
import type { HumanBrief } from "@/lib/types";
import { AnalysisRaw } from "./AnalysisRaw";
import { AnalysisSign } from "./AnalysisSign";
import type { BriefApproval } from "./briefApproval";
import { BriefApprove } from "./BriefApprove";
import { findingTitles } from "./briefs";

type View = "you" | "raw";

const VIEWS = [
  { value: "you", label: "For you" },
  { value: "raw", label: "Raw text" },
] as const;

/**
 * The analysis brief for the person who decides: For you is the sign (`AnalysisSign`), Raw text the
 * findings and the technical analysis as they were written. With `approval` the brief ends with
 * "Approve analysis" and the revision it approves, under either view. The choice of view lasts
 * while the brief is shown.
 */
export function AnalysisBriefView({
  brief,
  technical,
  approval,
}: {
  brief: HumanBrief;
  technical: unknown;
  approval?: BriefApproval | undefined;
}) {
  const idBase = useId();
  const [view, setView] = useState<View>("you");
  return (
    <div className="grid gap-4 text-sm">
      <div className="flex justify-end">
        <Segmented
          label="Brief view"
          value={view}
          options={VIEWS}
          onChange={setView}
          idBase={idBase}
        />
      </div>
      <SegmentedPanel idBase={idBase} value="you" active={view}>
        <AnalysisSign brief={brief} titles={findingTitles(technical)} />
      </SegmentedPanel>
      <SegmentedPanel idBase={idBase} value="raw" active={view}>
        <AnalysisRaw technical={technical} />
      </SegmentedPanel>
      {approval ? <BriefApprove approval={approval} /> : null}
    </div>
  );
}
