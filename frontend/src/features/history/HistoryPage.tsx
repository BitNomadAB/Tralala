import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import { keys, useBoard, useHistory } from "@/lib/queries";
import { renderMarkdown } from "@/lib/markdown";
import type { HistoryDetail, HistorySummary } from "@/lib/types";

export function HistoryPage() {
  const { boardId = "" } = useParams();
  const boardQuery = useBoard(boardId);
  const [q, setQ] = useState("");
  const [sourceKind, setSourceKind] = useState("");
  const [qaStatus, setQaStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const historyQuery = useHistory(boardId, {
    q: q.trim() || undefined,
    source_kind: sourceKind || undefined,
    qa_status: qaStatus || undefined,
  });

  const items: HistorySummary[] = historyQuery.data?.items ?? [];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to={`/boards/${boardId}`}
          className="inline-flex items-center gap-1 text-xs text-[var(--muted-foreground)] hover:underline"
        >
          <ArrowLeft size={13} /> {boardQuery.data?.name ?? "Board"}
        </Link>
        <h1 className="ml-1 text-lg font-semibold">Board history</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
            />
            <Input
              className="h-8 w-56 pl-8"
              placeholder="Search history"
              aria-label="Search history"
              value={q}
              onChange={(event) => setQ(event.target.value)}
            />
          </div>
          <Select
            className="h-8 w-auto"
            aria-label="Filter by source"
            value={sourceKind}
            onChange={(event) => setSourceKind(event.target.value)}
          >
            <option value="">Any source</option>
            <option value="native">Completed in Tralala</option>
            <option value="imported_legacy">Imported legacy</option>
          </Select>
          <Select
            className="h-8 w-auto"
            aria-label="Filter by QA status"
            value={qaStatus}
            onChange={(event) => setQaStatus(event.target.value)}
          >
            <option value="">Any QA status</option>
            <option value="accepted">QA accepted</option>
            <option value="unknown">Unknown</option>
          </Select>
        </div>
      </div>

      <p className="text-xs text-[var(--muted-foreground)]">
        {historyQuery.data?.meta?.total ?? items.length} record(s) ·{" "}
        {String(
          (historyQuery.data?.meta as { engine?: string } | undefined)?.engine ?? "like",
        )}{" "}
        search
      </p>

      {historyQuery.isLoading ? (
        <p className="text-sm text-[var(--muted-foreground)]">Loading history…</p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[var(--border)] p-4 text-xs text-[var(--muted-foreground)]">
          No historical records match this search.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((record) => (
            <li key={record.id}>
              <button
                type="button"
                className="card-surface flex w-full flex-wrap items-center gap-2 p-3 text-left hover:border-[var(--primary)]"
                onClick={() => setSelected(record.id)}
              >
                <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
                  {record.loop_key ?? "—"}
                </span>
                <span className="text-sm font-medium">{record.loop_name}</span>
                <Badge tone={record.source_kind === "native" ? "success" : "warning"}>
                  {record.source_kind === "native" ? "completed" : "imported legacy"}
                </Badge>
                <Badge tone={record.qa_status === "accepted" ? "success" : "neutral"}>
                  QA {record.qa_status}
                </Badge>
                <span className="ml-auto text-[11px] text-[var(--muted-foreground)]">
                  {new Date(record.completed_at ?? record.imported_at ?? record.created_at).toLocaleString()}
                </span>
                {record.label ? (
                  <span className="w-full text-[11px] text-[var(--warning)]">{record.label}</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}

      {selected ? (
        <HistoryRecordDialog
          boardId={boardId}
          historyId={selected}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </section>
  );
}

function HistoryRecordDialog({
  boardId,
  historyId,
  onClose,
}: {
  boardId: string;
  historyId: string;
  onClose: () => void;
}) {
  const detail = useQuery({
    queryKey: keys.historyRecord(boardId, historyId),
    queryFn: () => api.getHistoryRecord(boardId, historyId),
  });
  const record: HistoryDetail | undefined = detail.data;
  const documents = (
    (record?.envelope.documents as Array<{ kind: string; content: string }> | undefined) ?? []
  ).filter((document) => document.content);

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title={record ? record.loop_name : "History record"}
        description={
          record?.label || "Read-only snapshot captured when the Loop was completed."
        }
        className="w-[min(920px,96vw)]"
      >
        {detail.isLoading ? (
          <p className="text-sm text-[var(--muted-foreground)]">Loading record…</p>
        ) : !record ? (
          <p className="text-sm text-[var(--destructive)]">Record unavailable.</p>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
              <span className="font-mono">{record.loop_key ?? "imported"}</span>
              <span>QA {record.qa_status}</span>
              <span>hash {record.content_hash.slice(0, 12)}…</span>
            </div>
            {record.warnings.length > 0 ? (
              <ul className="rounded-lg border border-[var(--warning)] p-2 text-[11px] text-[var(--warning)]">
                {record.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            {documents.map((document) => (
              <section key={document.kind} className="flex flex-col gap-1">
                <h2 className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  {document.kind.replace("_", " ")}
                </h2>
                <div className="max-h-64 overflow-y-auto rounded-lg border border-[var(--border)] p-2 text-sm scrollbar-thin">
                  {renderMarkdown(document.content)}
                </div>
              </section>
            ))}
            {record.artifacts.length > 0 ? (
              <section className="flex flex-col gap-1">
                <h2 className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                  Evidence
                </h2>
                <ul className="text-[11px] text-[var(--muted-foreground)]">
                  {record.artifacts.map((artifact) => (
                    <li key={artifact.id}>
                      {artifact.filename} · {artifact.media_type} · {artifact.inclusion}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            <div className="flex justify-end">
              <Button variant="ghost" onClick={onClose}>
                Close
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
