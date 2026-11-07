import { KeyRound, Terminal } from "lucide-react";
import { REPOSITORY_SLUG_PLACEHOLDER, repositorySlug } from "@/lib/repositorySlug";

function Code({ children }: { children: string }) {
  return (
    <pre className="mt-1 overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)] p-2 font-mono text-[11px] leading-relaxed">
      <code>{children}</code>
    </pre>
  );
}

export function RepositoryTokenGuide({ url }: { url: string }) {
  const slug = repositorySlug(url);
  const hasRepository = slug !== REPOSITORY_SLUG_PLACEHOLDER;
  const keyName = slug.replace("/", "-").toLowerCase();

  return (
    <details className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs">
      <summary className="flex cursor-pointer items-center gap-1.5 font-medium">
        <KeyRound size={13} /> How do I create the key?
      </summary>

      <div className="mt-2 flex flex-col gap-3 text-[var(--muted-foreground)]">
        <p>
          Tralala reads files through GitHub&apos;s REST API over HTTPS, so the field above takes a{" "}
          <strong>read-only access token</strong>. It is never a password, and a token cannot be
          generated on your machine — GitHub issues it, you paste it here once.
        </p>
        <p className="text-[11px] italic">
          {hasRepository ? (
            <>
              The steps name the repository in the URL field (
              <span className="font-mono">{slug}</span>); they fit any repository you add here.
            </>
          ) : (
            <>
              The steps show placeholders; fill in the URL field above and they will name your
              repository instead.
            </>
          )}
        </p>

        <div>
          <p className="font-medium text-[var(--foreground)]">1. Create a fine-grained token</p>
          <ol className="mt-1 list-decimal gap-1 pl-4">
            <li>
              Open{" "}
              <a
                className="underline"
                href="https://github.com/settings/personal-access-tokens/new"
                target="_blank"
                rel="noreferrer"
              >
                github.com/settings/personal-access-tokens/new
              </a>
              .
            </li>
            <li>
              <strong>Resource owner</strong>: the user or organisation that owns{" "}
              <span className="font-mono">{slug}</span>. For an organisation&apos;s repository pick
              the organisation, not yourself; it may have to approve the token before it works.
            </li>
            <li>
              <strong>Repository access</strong>: <em>Only select repositories</em>, then pick{" "}
              <span className="font-mono">{slug}</span>. One token per repository keeps the damage
              small if it leaks. A token created without choosing repositories reads public
              repositories only, so a private one answers as if it did not exist.
            </li>
            <li>
              <strong>Permissions</strong> &rarr; <em>Repository permissions</em> &rarr;{" "}
              <em>Contents</em>: <strong>Read-only</strong>. Leave everything else untouched
              (Metadata follows automatically).
            </li>
            <li>
              <strong>Expiration</strong>: as short as your workflow allows. A token that expires is
              a token that cannot be forgotten.
            </li>
            <li>Generate the token and copy it now — GitHub shows it once.</li>
          </ol>
        </div>

        <div>
          <p className="flex items-center gap-1.5 font-medium text-[var(--foreground)]">
            <Terminal size={13} /> 2. Check it on your machine before pasting
          </p>
          <p className="mt-1">
            This reads the newest commit, as a run does. A 200 means the key can read the code; 401
            means wrong or expired; 404 means it cannot see this repository or its contents.
          </p>
          <Code>{`# bash, macOS, Linux
export GITHUB_TOKEN=github_pat_...
curl -sS -o /dev/null -w "%{http_code}\\n" \\
  -H "Authorization: Bearer $GITHUB_TOKEN" \\
  https://api.github.com/repos/${slug}/commits/HEAD`}</Code>
          <Code>{`# PowerShell
$env:GITHUB_TOKEN = "github_pat_..."
(Invoke-WebRequest -Uri "https://api.github.com/repos/${slug}/commits/HEAD" \`
  -Headers @{ Authorization = "Bearer $env:GITHUB_TOKEN" }).StatusCode`}</Code>
        </div>

        <div>
          <p className="font-medium text-[var(--foreground)]">3. Store it here</p>
          <p className="mt-1">
            Paste it into <em>Access token</em> and press <em>Save repository</em>: Tralala checks
            access at once, reading the code the way a run does, and <em>Test access</em> repeats
            the check. Tralala seals it with the installation secret, keeps only a short hint, and
            never returns it again. To rotate, open <em>Edit</em>, paste the new token and save —
            the old one is replaced, not added.
          </p>
        </div>

        <div>
          <p className="font-medium text-[var(--foreground)]">
            4. One key for several repositories
          </p>
          <p className="mt-1">
            A repository entry holds one token for one repository, which is what a board needs. An
            organisation profile such as the Architect reads the whole picture, so give that agent a
            token of its own: same recipe, but <em>Repository access</em> ={" "}
            <em>All repositories</em> (or every repository of one owner), still{" "}
            <em>Contents: Read-only</em>. Keep it separate from the tokens you enter here so one
            leak cannot spread.
          </p>
        </div>

        <div>
          <p className="font-medium text-[var(--foreground)]">
            5. SSH deploy key instead? Not for this field
          </p>
          <p className="mt-1">
            An SSH key gives a <em>git client</em> access and is issued locally with{" "}
            <span className="font-mono">ssh-keygen</span>. Tralala never uses SSH, not even for a
            Git over HTTPS mirror, so it cannot read one. Keep it for your own clone on the machine
            that runs an agent:
          </p>
          <Code>{`ssh-keygen -t ed25519 -f ~/.ssh/${keyName} -C "analysis-agent"
# register the .pub file as a Deploy Key at
# https://github.com/${slug}/settings/keys
GIT_SSH_COMMAND="ssh -i ~/.ssh/${keyName} -o IdentitiesOnly=yes" \\
  git clone git@github.com:${slug}.git`}</Code>
          <p className="mt-1">
            Tick <em>Allow write access</em> only if that clone must push. For analysis, read access
            is enough.
          </p>
        </div>

        <p className="border-t border-[var(--border)] pt-2 text-[11px]">
          A token inherits the rights of the account that created it. Use a dedicated bot account or
          the smallest scope that works, never commit the value anywhere, and remove the token in
          GitHub when the installation no longer needs it.
        </p>
      </div>
    </details>
  );
}
