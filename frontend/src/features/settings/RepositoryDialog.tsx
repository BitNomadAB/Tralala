import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import type { RepositoryProvider } from "@/lib/types";
import { PROVIDER_LABELS } from "./repositoryLabels";
import { RepositoryTokenGuide } from "./RepositoryTokenGuide";

/** A repository as the dialog edits it; `id` is null for a new one and a blank token keeps the stored one. */
export interface RepositoryDraft {
  id: string | null;
  name: string;
  /** Chosen when the repository is added; an existing repository keeps its provider. */
  provider: RepositoryProvider;
  url: string;
  branch: string;
  token: string;
  enabled: boolean;
}

/** What each provider reads and what its fields take. */
const PROVIDER_TEXT: Record<
  RepositoryProvider,
  { description: string; placeholder: string; branch: string; token: string }
> = {
  github: {
    description:
      "Read-only access for the Analysis agent through the GitHub API. Only https://github.com/your-org/your-repo is accepted.",
    placeholder: "https://github.com/your-org/your-repo",
    branch: "Defaults to the default branch.",
    token:
      "Not needed for a public repository: without one GitHub allows 60 calls an hour per address, a token raises that to 5 000. For a private repository: a fine-grained token with Contents: read for this repository only.",
  },
  git_https: {
    description:
      "Tralala keeps a mirror of the main branch and fetches it before every analysis. Any https Git URL on a host listed in TRALALA_REPOSITORY_HOSTS is accepted; nothing from the repository is ever run.",
    placeholder: "https://git.example.com/team/app.git",
    branch: "Defaults to the branch the remote's HEAD names (main, master, ...).",
    token:
      "A read-only token, if the host needs one. It is sent as the password of user x-access-token; write user:token for a host that checks the user name.",
  },
};

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
  const text = PROVIDER_TEXT[draft.provider];

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title={draft.id ? "Edit repository" : "New repository"}
        description={text.description}
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.url.trim()) onSave();
          }}
        >
          <Field
            label="Provider"
            htmlFor="repository-provider"
            hint={draft.id ? "A repository keeps the provider it was added with." : undefined}
          >
            <Select
              id="repository-provider"
              value={draft.provider}
              disabled={draft.id !== null}
              onChange={(event) =>
                update({ provider: event.target.value === "git_https" ? "git_https" : "github" })
              }
            >
              <option value="github">{PROVIDER_LABELS.github}</option>
              <option value="git_https">{PROVIDER_LABELS.git_https}</option>
            </Select>
          </Field>
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
              placeholder={text.placeholder}
              required
              maxLength={500}
            />
          </Field>
          <Field label="Branch (optional)" htmlFor="repository-branch" hint={text.branch}>
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
                : text.token
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
          {draft.provider === "github" ? <RepositoryTokenGuide url={draft.url} /> : null}
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
