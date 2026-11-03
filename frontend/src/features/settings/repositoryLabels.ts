import type { RepositoryProvider } from "@/lib/types";

/** How each provider is named on the Repositories page and in its dialog. */
export const PROVIDER_LABELS: Record<RepositoryProvider, string> = {
  github: "GitHub",
  git_https: "Git over HTTPS",
};

/** A mirror's size on disk: "512 B", "48 KB", "3.4 MB", "1.2 GB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["MB", "GB"] as const;
  let value = bytes / 1024;
  let unit = "KB";
  for (const next of units) {
    if (value < 1024) break;
    value /= 1024;
    unit = next;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${unit}`;
}
