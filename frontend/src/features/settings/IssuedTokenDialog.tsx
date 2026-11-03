import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { Credential } from "@/lib/types";

/** Shows a newly issued token once; the server keeps only its hash. */
export function IssuedTokenDialog({
  issued,
  onClose,
  onCopy,
}: {
  issued: Credential | null;
  onClose: () => void;
  onCopy: () => void;
}) {
  return (
    <Dialog open={Boolean(issued)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title="Copy this token now"
        description="The server stores only a hash. It cannot be shown again."
      >
        <div className="flex items-center gap-2">
          <Input readOnly value={issued?.token ?? ""} aria-label="New API token" />
          <Button size="icon" variant="secondary" aria-label="Copy token" onClick={onCopy}>
            <Copy size={14} />
          </Button>
        </div>
        <p className="mt-3 text-[11px] text-[var(--muted-foreground)]">
          Paste it into your MCP client as <code>Authorization: Bearer &lt;token&gt;</code>. The
          card above now shows the config with this token filled in.
        </p>
        <div className="mt-3 flex justify-end">
          <Button onClick={onClose}>Done</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
