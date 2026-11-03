import { Button } from "@/components/ui/button";

/**
 * Asked instead of saving Info while a generation run is in flight.
 *
 * The server never promotes a result written from an Info that has since changed, so a save during a
 * run quietly turned minutes of generation into a failed run. The person chooses: stop the run and
 * save, or save and let the run end with its result kept for inspection only.
 */
export function InfoSaveGuard({
  pending,
  onCancelRunFirst,
  onSaveAnyway,
  onBack,
}: {
  pending: boolean;
  onCancelRunFirst: () => void;
  onSaveAnyway: () => void;
  onBack: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <span role="alert" className="text-[11px] text-[var(--warning)]">
        A generation run is in progress; saving now discards its result, which is only kept for
        inspection.
      </span>
      <Button size="sm" disabled={pending} onClick={onCancelRunFirst} autoFocus>
        Cancel the run first
      </Button>
      <Button size="sm" variant="outline" disabled={pending} onClick={onSaveAnyway}>
        Save anyway
      </Button>
      <Button size="sm" variant="ghost" disabled={pending} onClick={onBack}>
        Back
      </Button>
    </div>
  );
}
