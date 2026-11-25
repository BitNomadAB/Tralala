import { ChevronRight, Copy, Laptop } from "lucide-react";
import { claudeCodeCommand, MCP_REVISION } from "@/lib/agentAccess";

/** The placeholder is the installation's own address, so the guide carries no host of its own. */
const PLACEHOLDER_ORIGIN = "https://<Your URL>";
const PLACEHOLDER_TOKEN = "<your-token>";

/** A block to paste; a long line scrolls sideways, so it takes focus for a keyboard to scroll it. */
function Code({ children }: { children: string }) {
  return (
    <pre
      role="group"
      aria-label="Code block"
      tabIndex={0}
      className="mt-1 overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)] p-2 font-mono text-xs leading-relaxed"
    >
      <code>{children}</code>
    </pre>
  );
}

function Mono({ children }: { children: string }) {
  return <span className="font-mono">{children}</span>;
}

/**
 * The five steps between "I have a key" and "my agent is working".
 *
 * Deliberately short and self-contained: the person reading it is at their own machine, not in the
 * Tralala UI, so it names the exact command to run and what a failure looks like. The command is
 * Claude Code's, because `/mcp` speaks one MCP revision and Claude Code is the client whose own
 * documentation says it speaks it; the copy button copies the command exactly as it is shown.
 */
export function AgentAccessGuide({
  token,
  onCopy,
}: {
  token?: string | undefined;
  onCopy?: (command: string) => void;
}) {
  const command = claudeCodeCommand(PLACEHOLDER_ORIGIN, token ?? PLACEHOLDER_TOKEN);
  return (
    <details className="group rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs">
      {/* A flex summary loses the browser's own triangle, so it draws one that turns when open. */}
      <summary className="flex cursor-pointer items-center gap-1.5 font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight
          size={13}
          aria-hidden="true"
          className="shrink-0 group-open:rotate-90 motion-safe:transition-transform"
        />
        <Laptop size={13} aria-hidden="true" /> How do I connect my computer?
      </summary>

      <div className="mt-2 flex flex-col gap-3 text-[var(--muted-foreground)]">
        <ol className="flex list-decimal flex-col gap-2 pl-4">
          <li>
            <strong className="text-[var(--foreground)]">Create the key for this machine.</strong>{" "}
            Press <em>New access key</em> above and name it after the machine — &quot;laptop
            work&quot;, &quot;home desktop&quot;. Tick the scopes the agent needs:{" "}
            <Mono>boards:read</Mono>, <Mono>cards:read</Mono>, <Mono>loops:read</Mono> to look
            around; add <Mono>cards:write</Mono>, <Mono>comments:write</Mono> to track Tickets, and{" "}
            <Mono>loops:write</Mono>, <Mono>loops:generate</Mono> to start Loops and analyses.
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Copy the token.</strong> It is shown once;
            the server keeps only a hash. Treat it like a password and never commit it to a
            repository.
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Add Tralala to Claude Code.</strong> Your
            agent must speak MCP {MCP_REVISION}: Tralala speaks that revision of the Model Context
            Protocol and no older one. Claude Code&apos;s own documentation says it does from
            version 2.1.274; <Mono>claude --version</Mono> prints yours, and{" "}
            <Mono>claude update</Mono> installs the newest. In the folder of the project you will
            work on, run this command with <Mono>{PLACEHOLDER_ORIGIN}</Mono> replaced by the address
            you use to open Tralala
            {token ? null : (
              <>
                {" "}
                and <Mono>{PLACEHOLDER_TOKEN}</Mono> by the token
              </>
            )}
            :<Code>{command}</Code>
            {onCopy ? (
              <button
                type="button"
                onClick={() => onCopy(command)}
                className="mt-1 inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--surface)]"
              >
                <Copy size={12} /> Copy this command
              </button>
            ) : null}
            <p className="mt-2 text-xs">
              Claude Code keeps the server for that folder; start a new session there. Another
              client takes the same address and the same <Mono>Authorization</Mono> header in its
              own configuration, once it speaks {MCP_REVISION}.
            </p>
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Check that it works.</strong>{" "}
            <Mono>claude mcp list</Mono> shows <Mono>tralala</Mono> as connected, and when you ask
            Claude to call Tralala&apos;s <Mono>whoami</Mono>, it answers with your key&apos;s name.
            When it does not connect: <Mono>401</Mono> means the token is wrong, revoked or expired;{" "}
            <Mono>400</Mono> or <Mono>405</Mono> with a message that names MCP {MCP_REVISION} means
            the client tried an older revision; <Mono>403</Mono> means the request carried an{" "}
            <Mono>Origin</Mono> header that Tralala does not trust. A missing scope stops no
            connection: the agent does not see the tools that scope opens, and a call to one comes
            back with the error <Mono>Missing required scope: …</Mono> in its answer, not with a{" "}
            <Mono>403</Mono>.
          </li>
          <li>
            <strong className="text-[var(--foreground)]">Watch &quot;last used&quot; here.</strong>{" "}
            It updates on every call, so you can see that it is your machine connecting and nobody
            else. Revoke the key when the work is finished; disabling your account stops it too.
          </li>
        </ol>
        <p className="text-xs italic">
          The endpoint is <Mono>{"<Your URL>/mcp"}</Mono> and speaks MCP {MCP_REVISION} alone; its
          tool list is described in plain text at <Mono>{"<Your URL>/llms.txt"}</Mono>. Agent usage,
          in Tralala&apos;s documentation, says which clients can connect and what to try when one
          does not.
        </p>
      </div>
    </details>
  );
}
