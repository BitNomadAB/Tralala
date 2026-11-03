import { Field, Textarea } from "@/components/ui/input";
import type { RepositoryPathsDraft } from "./repositoryPaths";

/**
 * The focus and exclude globs of one selected repository, one glob per line. They narrow what a
 * Loop's analysis reads of it; both empty reads the whole repository.
 */
export function RepositoryPathFields({
  repositoryId,
  repositoryName,
  value,
  onChange,
  disabled,
}: {
  repositoryId: string;
  repositoryName: string;
  value: RepositoryPathsDraft;
  onChange: (value: RepositoryPathsDraft) => void;
  disabled?: boolean | undefined;
}) {
  const id = `repository-paths-${repositoryId}`;
  return (
    <div className="ml-6 flex flex-col gap-1.5">
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label={`Focus paths in ${repositoryName}`} htmlFor={`${id}-focus`}>
          <Textarea
            id={`${id}-focus`}
            className="min-h-16 font-mono text-xs"
            rows={2}
            placeholder="docs/**"
            spellCheck={false}
            value={value.focus}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, focus: event.target.value })}
          />
        </Field>
        <Field label={`Exclude paths in ${repositoryName}`} htmlFor={`${id}-exclude`}>
          <Textarea
            id={`${id}-exclude`}
            className="min-h-16 font-mono text-xs"
            rows={2}
            placeholder="docs/archive/**"
            spellCheck={false}
            value={value.exclude}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, exclude: event.target.value })}
          />
        </Field>
      </div>
      <p className="text-[11px] text-[var(--muted-foreground)]">
        One glob per line, relative to the repository root; <code>*</code> also crosses folders.
        With focus paths only matching files are read; excluded files never are. Both empty reads
        the whole repository.
      </p>
    </div>
  );
}
