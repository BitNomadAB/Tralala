import { HeldButton } from "@/components/ui/held-button";

/**
 * Asked instead of saving Info while a generation run is in flight.
 *
 * The server never promotes a result written from an Info that has since changed, so a save during a
 * run quietly turned minutes of generation into a failed run. The person chooses: stop the run and
 * save, or save and let the run end with its result kept for inspection only. The pressed choice
 * keeps the focus while it works, and the editor takes it back once the question has gone.
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
      <span role="alert" className="text-xs text-[var(--warning)]">
        A generation run is in progress; saving now discards its result, which is only kept for
        inspection.
      </span>
      <HeldButton size="sm" held={pending} onClick={onCancelRunFirst} autoFocus>
        Cancel the run first
      </HeldButton>
      <HeldButton size="sm" variant="outline" held={pending} onClick={onSaveAnyway}>
        Save anyway
      </HeldButton>
      <HeldButton size="sm" variant="ghost" held={pending} onClick={onBack}>
        Back
      </HeldButton>
    </div>
  );
}
