import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { RepositoryTokenGuide } from "./RepositoryTokenGuide";

/** A repository as the dialog edits it; `id` is null for a new one and a blank token keeps the stored one. */
export interface RepositoryDraft {
  id: string | null;
  name: string;
  url: string;
  branch: string;
  token: string;
  enabled: boolean;
}

export function RepositoryDialog({
  draft,
  saving,
  hasToken,
  onChange,
  onClose,
  onSave,
}: {
  draft: RepositoryDraft;
  saving: boolean;
  hasToken: boolean;
  onChange: (value: RepositoryDraft) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const update = (patch: Partial<RepositoryDraft>) => {
    onChange({ ...draft, ...patch });
  };

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title={draft.id ? "Edit repository" : "New repository"}
        description="Read-only access for the Analysis agent. Only https://github.com/your-org/your-repo is accepted."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.url.trim()) onSave();
          }}
        >
          <Field
            label="Name"
            htmlFor="repository-name"
            hint="Shown in lists; defaults to the repository name."
          >
            <Input
              id="repository-name"
              value={draft.name}
              onChange={(event) => update({ name: event.target.value })}
              maxLength={120}
            />
          </Field>
          <Field label="Repository URL" htmlFor="repository-url">
            <Input
              id="repository-url"
              value={draft.url}
              onChange={(event) => update({ url: event.target.value })}
              placeholder="https://github.com/your-org/your-repo"
              required
              maxLength={500}
            />
          </Field>
          <Field
            label="Branch (optional)"
            htmlFor="repository-branch"
            hint="Defaults to the default branch."
          >
            <Input
              id="repository-branch"
              value={draft.branch}
              onChange={(event) => update({ branch: event.target.value })}
              placeholder="main"
              maxLength={200}
            />
          </Field>
          <Field
            label="Access token"
            htmlFor="repository-token"
            hint={
              hasToken
                ? "A token is stored. Leave blank to keep it; enter a new one to replace it."
                : "Fine-grained token with Contents: read for this repository only."
            }
          >
            <Input
              id="repository-token"
              type="password"
              value={draft.token}
              onChange={(event) => update({ token: event.target.value })}
              autoComplete="off"
              maxLength={500}
            />
          </Field>
          <RepositoryTokenGuide url={draft.url} />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => update({ enabled: event.target.checked })}
            />
            Enabled for analysis
          </label>
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={!draft.url.trim() || saving}>
              Save repository
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
