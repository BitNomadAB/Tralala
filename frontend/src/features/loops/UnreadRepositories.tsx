import { AlertTriangle } from "lucide-react";
import { repositoryReading, unreadRepositories } from "@/lib/runPhases";
import type { GenerationRun } from "@/lib/types";

/**
 * The warning a run without (part of) its code carries above its stages: what it goes on without and
 * what to do, in the server's sentence. The run itself goes on, so this line is what keeps a finished
 * "Done" from reading as "the code was read".
 */
export function UnreadRepositories({ run, compact }: { run: GenerationRun; compact: boolean }) {
  const unread = unreadRepositories(run);
  if (unread.length === 0) return null;
  const none = repositoryReading(run) === "unread";
  return (
    <div
      role="note"
      aria-label={none ? "Written without the code" : "Part of the code was not read"}
      className={`flex flex-col gap-1 rounded-md border border-[var(--warning)] bg-[var(--surface-raised)] p-2 text-[var(--warning)] ${
        compact ? "text-[11px]" : "text-xs"
      }`}
    >
      <p className="flex items-center gap-1.5 font-medium">
        <AlertTriangle size={12} aria-hidden />
        {none ? "Written without the code" : "Part of the code was not read"}
      </p>
      {unread.map((repository) => (
        <p key={repository.name} className="text-[var(--foreground)]">
          {repository.problem}
        </p>
      ))}
    </div>
  );
}
