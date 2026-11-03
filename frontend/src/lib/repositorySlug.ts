const REPOSITORY_PATTERN = /^https:\/\/github\.com\/([^/\s]+)\/([^/\s]+?)(?:\.git)?\/?$/i;

/** Neutral placeholder: the guide never carries an example repository of its own. */
export const REPOSITORY_SLUG_PLACEHOLDER = "your-org/your-repo";

/** `owner/repository` from the URL field, so the guide can name the exact pages. */
export function repositorySlug(url: string): string {
  const [, owner, repository] = REPOSITORY_PATTERN.exec(url.trim()) ?? [];
  return owner !== undefined && repository !== undefined
    ? `${owner}/${repository}`
    : REPOSITORY_SLUG_PLACEHOLDER;
}
