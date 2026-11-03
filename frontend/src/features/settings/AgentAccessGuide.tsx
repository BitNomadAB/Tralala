import { Copy, Laptop } from "lucide-react";
import { mcpConfigSnippet } from "@/lib/agentAccess";

/** The placeholder is the installation's own address, so the guide carries no host of its own. */
const PLACEHOLDER_ORIGIN = "https://<Your URL>";

function Code({ children }: { children: string }) {
  return (
    <pre className="mt-1 overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)] p-2 font-mono text-[11px] leading-relaxed">
      <code>{children}</code>
    </pre>
  );
}

/**
 * The five steps between "I have a key" and "my agent is working".
 *
 * Deliberately short and self-contained: the person reading it is at their own machine, not in the
 * Tralala UI, so it names the exact block to paste and what a failure looks like.
 */
export function AgentAccessGuide({
  token,
  onCopy,
}: {
  token?: string | undefined;
  onCopy?: (snippet: string) => void;
}) {
  const snippet = mcpConfigSnippet(PLACEHOLDER_ORIGIN, token ?? "<your-token>");
  return (
    <details className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs">
      <summary className="flex cursor-pointer items-center gap-1.5 font-medium">
        <Laptop size={13} /> How do I connect my computer?
      </summary>

      <div className="mt-2 flex flex-col gap-3 text-[var(--muted-foreground)]">
        <ol className="flex list-decimal flex-col gap-2 pl-4">
          <li>
            <strong className="text-[var(--foreground)]">Create the key for this machine.</strong>{" "}
            Press <em>New access key</em> above and name it after the machine — &quot;laptop
            work&quot;, &quot;desktop copilot&quot;. Tick the scopes the agent needs:{" "}
            <span className="font-mono">boards:read</span>,{" "}
            <span className="font-mono">cards:read</span>,{" "}
            <span className="font-mono">loops:read</span> to look around; add{" "}
            <span className="font-mono">cards:write</span>,{" "}
            <span className="font-mono">comments:write</span> to track Tickets, and{" "}
            <span className="font-mono">loops:write</span>,{" "}
            <span className="font-mono">loops:generate</span> to start Loops and analyses.
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Copy the token.</strong> It is shown once;
            the server keeps only a hash. Treat it like a password and never commit it to a
            repository.
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Paste it into your agent&apos;s MCP
            configuration</strong> — in VS Code that is the <em>mcp.json</em> file. The block below
            is complete apart from the address and the token: replace{" "}
            <span className="font-mono">{"<Your URL>"}</span> with the address you use to open
            Tralala, which is normally <span className="font-mono">https://…</span> over a tailnet or
            behind a proxy.
            <Code>{snippet}</Code>
            <p className="mt-2 text-[11px]">
              <span className="font-mono">type</span> names the transport (Streamable HTTP), not the
              scheme — keep <span className="font-mono">http</span> even when the address is{" "}
              <span className="font-mono">https://</span>. The scheme lives in{" "}
              <span className="font-mono">url</span>.
            </p>
            {onCopy ? (
              <button
                type="button"
                onClick={() => onCopy(snippet)}
                className="mt-1 inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2 py-1 text-[11px] hover:bg-[var(--surface)]"
              >
                <Copy size={12} /> Copy this block
              </button>
            ) : null}
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Ask the agent to read a board.</strong> If
            it answers with your boards, the connection works. When it does not:{" "}
            <span className="font-mono">401</span> means the token is wrong, revoked or expired, and{" "}
            <span className="font-mono">403</span> means the key is missing a scope.
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Watch &quot;last used&quot; here.</strong>{" "}
            It updates on every call, so you can see that it is your machine connecting and nobody
            else. Revoke the key when the work is finished; disabling your account stops it too.
          </li>
        </ol>
        <p className="text-[11px] italic">
          The endpoint is <span className="font-mono">{"<Your URL>"}/mcp</span>; its tool list is
          described in plain text at <span className="font-mono">{"<Your URL>"}/llms.txt</span>.
        </p>
      </div>
    </details>
  );
}
