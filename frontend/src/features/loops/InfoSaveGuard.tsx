import { BusyButton } from "./BusyButton";

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
      <span role="alert" className="text-[11px] text-[var(--warning)]">
        A generation run is in progress; saving now discards its result, which is only kept for
        inspection.
      </span>
      <BusyButton size="sm" busy={pending} onClick={onCancelRunFirst} autoFocus>
        Cancel the run first
      </BusyButton>
      <BusyButton size="sm" variant="outline" busy={pending} onClick={onSaveAnyway}>
        Save anyway
      </BusyButton>
      <BusyButton size="sm" variant="ghost" busy={pending} onClick={onBack}>
        Back
      </BusyButton>
    </div>
  );
}
