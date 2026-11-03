import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Bot, CheckSquare, Circle, CircleCheck, Send, User } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { Badge, LabelChip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { useCardEvents } from "@/features/cards/useCardEvents";
import { ApiError, api } from "@/lib/api";
import { renderMarkdown } from "@/lib/markdown";
import { activeMention, applyMention, matchingAgents, type MentionToken } from "@/lib/mentions";
import { keys, useActivity, useLabels } from "@/lib/queries";
import {
  PRIORITIES,
  type AgentDirectoryEntry,
  type BoardList,
  type ChecklistItem,
  type MentionJob,
  type Priority,
} from "@/lib/types";
import { formatDateTime, fromDateInputValue, toDateInputValue } from "@/lib/utils";
import { useCardTools } from "@/webmcp/useWebMcp";

const MENTION_TONES: Record<MentionJob["status"], "neutral" | "brand" | "success" | "danger"> = {
  queued: "neutral",
  running: "brand",
  completed: "success",
  failed: "danger",
};

interface Draft {
  title: string;
  description: string;
  priority: Priority;
  due: string;
  labels: string[];
}

export function CardDialog({
  boardId,
  loopId,
  cardId,
  lists,
  onClose,
  onConfirmHuman,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  lists: BoardList[];
  onClose: () => void;
  onConfirmHuman?: (version: number, note: string) => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: card, isLoading, error } = useQuery({
    queryKey: keys.card(boardId, loopId, cardId),
    queryFn: () => api.getCard(boardId, loopId, cardId),
  });
  const labelsQuery = useLabels(boardId);
  const activityQuery = useActivity(boardId, cardId);
  const agentsQuery = useQuery({
    queryKey: keys.agentDirectory,
    queryFn: () => api.listAgentDirectory(),
  });
  const mentionsQuery = useQuery({
    queryKey: keys.mentions(boardId, loopId, cardId),
    queryFn: () => api.listMentions(boardId, loopId, cardId),
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [preview, setPreview] = useState(false);
  const [comment, setComment] = useState("");
  const [mentionToken, setMentionToken] = useState<MentionToken | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const commentField = useRef<HTMLTextAreaElement | null>(null);
  const [checklistTitle, setChecklistTitle] = useState("");
  const [itemText, setItemText] = useState<Record<string, string>>({});

  // The draft starts from the card once it has loaded; set while rendering, not in an effect.
  if (card && !draft) {
    setDraft({
      title: card.title,
      description: card.description,
      priority: card.priority,
      due: toDateInputValue(card.due_at),
      labels: card.labels.map((label) => label.id),
    });
  }

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.card(boardId, loopId, cardId) });
    void queryClient.invalidateQueries({ queryKey: keys.loopCardsPrefix(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.activity(boardId, cardId) });
    void queryClient.invalidateQueries({ queryKey: keys.activity(boardId) });
    void queryClient.invalidateQueries({ queryKey: keys.mentions(boardId, loopId, cardId) });
  }, [queryClient, boardId, loopId, cardId]);

  const live = useCardEvents(boardId, loopId, cardId, refresh);

  const onError = (mutationError: unknown) => {
    toast.push({
      title: "Change rejected",
      description:
        mutationError instanceof ApiError
          ? mutationError.code === "version_conflict"
            ? "Someone else updated this card. Reload to see the latest version."
            : mutationError.message
          : undefined,
      variant: "error",
    });
    refresh();
  };

  const updateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.updateCard>[3]) =>
      api.updateCard(boardId, loopId, cardId, payload),
    onSuccess: refresh,
    onError,
  });

  const moveMutation = useMutation({
    mutationFn: (listId: string) =>
      api.moveCard(boardId, loopId, cardId, {
        version: card?.version ?? 1,
        list_id: listId,
        position: 10_000,
      }),
    onSuccess: refresh,
    onError,
  });

  const archiveMutation = useMutation({
    mutationFn: () => api.archiveCard(boardId, loopId, cardId),
    onSuccess: () => {
      refresh();
      onClose();
      toast.push({ title: "Card archived", variant: "success" });
    },
    onError,
  });

  const checklistMutation = useMutation({
    mutationFn: (title: string) => api.addChecklist(boardId, loopId, cardId, title),
    onSuccess: () => {
      setChecklistTitle("");
      refresh();
    },
    onError,
  });

  const itemMutation = useMutation({
    mutationFn: ({ checklistId, text }: { checklistId: string; text: string }) =>
      api.addChecklistItem(boardId, checklistId, text),
    onSuccess: () => {
      setItemText({});
      refresh();
    },
    onError,
  });

  const toggleItemMutation = useMutation({
    mutationFn: (item: ChecklistItem) =>
      api.updateChecklistItem(boardId, item.id, { completed: !item.completed }),
    onSuccess: refresh,
    onError,
  });

  const commentMutation = useMutation({
    mutationFn: (content: string) => api.addComment(boardId, loopId, cardId, content),
    onSuccess: () => {
      setComment("");
      setMentionToken(null);
      refresh();
    },
    onError,
  });

  const retryMentionMutation = useMutation({
    mutationFn: (jobId: string) => api.retryMention(boardId, loopId, cardId, jobId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.mentions(boardId, loopId, cardId) }),
    onError,
  });

  const suggestions = useMemo(
    () =>
      mentionToken
        ? matchingAgents(agentsQuery.data ?? [], mentionToken.query).slice(0, 6)
        : [],
    [mentionToken, agentsQuery.data],
  );

  function chooseAgent(agent: AgentDirectoryEntry) {
    if (!mentionToken) return;
    const next = applyMention(comment, mentionToken, agent.name);
    setComment(next.text);
    setMentionToken(null);
    setMentionIndex(0);
    requestAnimationFrame(() => {
      commentField.current?.focus();
      commentField.current?.setSelectionRange(next.caret, next.caret);
    });
  }

  useCardTools({
    boardId,
    loopId,
    cardId,
    onOpen: () => undefined,
    onClose,
  });

  const labelOptions = useMemo(() => labelsQuery.data ?? [], [labelsQuery.data]);

  const dirty =
    draft && card
      ? draft.title !== card.title ||
        draft.description !== card.description ||
        draft.priority !== card.priority ||
        draft.due !== toDateInputValue(card.due_at) ||
        draft.labels.slice().sort().join() !== card.labels.map((l) => l.id).sort().join()
      : false;

  function save() {
    if (!draft || !card) return;
    updateMutation.mutate({
      version: card.version,
      title: draft.title.trim(),
      description: draft.description,
      priority: draft.priority,
      due_at: draft.due ? (fromDateInputValue(draft.due) ?? undefined) : undefined,
      clear_due_at: draft.due === "",
      labels: draft.labels,
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={card?.title ?? "Card"}
        description={card ? `Updated ${formatDateTime(card.updated_at)} · version ${card.version}` : undefined}
        className="w-[min(760px,96vw)]"
      >
        {isLoading || !draft ? (
          <p className="text-sm text-[var(--muted-foreground)]">Loading card…</p>
        ) : error || !card ? (
          <p role="alert" className="text-sm text-[var(--destructive)]">
            {error instanceof ApiError ? error.message : "Card unavailable."}
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {card.ticket_key || card.human_action_required || card.blockers.length > 0 ? (
              <div className="flex flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2 text-[11px]">
                <div className="flex flex-wrap items-center gap-2">
                  {card.ticket_key ? (
                    <span className="font-mono text-[var(--muted-foreground)]">{card.ticket_key}</span>
                  ) : null}
                  {card.phase_number ? <Badge tone="neutral">Phase {card.phase_number}</Badge> : null}
                  {card.human_action_required ? (
                    <Badge tone="warning">
                      <User size={11} /> Human action required
                    </Badge>
                  ) : null}
                  {card.ready ? null : <Badge tone="neutral">Blocked</Badge>}
                </div>
                {card.human_action_required && card.human_action_reason ? (
                  <p className="text-[var(--muted-foreground)]">
                    Why a human is needed: {card.human_action_reason}
                  </p>
                ) : null}
                {card.human_action_required && card.human_instructions ? (
                  <p className="text-[var(--muted-foreground)]">
                    What to do: {card.human_instructions}
                  </p>
                ) : null}
                {card.human_action_required && card.downstream_phase_numbers.length > 0 ? (
                  <p className="text-[var(--muted-foreground)]">
                    Phase {card.downstream_phase_numbers.join(", ")} and its dependent phases cannot
                    start until a human confirms this action.
                  </p>
                ) : null}
                {!card.ready && card.blockers.length > 0 ? (
                  <p className="text-[var(--warning)]">
                    Blocked by:{" "}
                    {card.blockers
                      .map((blocker) =>
                        blocker.type === "phase"
                          ? `Phase ${blocker.phase_number ?? "?"}`
                          : (blocker.key ?? blocker.title ?? "Ticket"),
                      )
                      .join(", ")}
                  </p>
                ) : null}
                {card.acceptance_criteria.length > 0 ? (
                  <p className="text-[var(--muted-foreground)]">
                    Accepted when: {card.acceptance_criteria.join("; ")}
                  </p>
                ) : null}
                {card.expected_evidence.length > 0 ? (
                  <p className="text-[var(--muted-foreground)]">
                    Evidence: {card.expected_evidence.join("; ")}
                  </p>
                ) : null}
              </div>
            ) : null}
            <div className="grid gap-3 md:grid-cols-[1fr_200px]">
              <div className="flex flex-col gap-2">
                <Field label="Title" htmlFor="card-title">
                  <Input
                    id="card-title"
                    value={draft.title}
                    onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                  />
                </Field>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                    Description
                  </span>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant={preview ? "ghost" : "secondary"}
                      onClick={() => setPreview(false)}
                    >
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant={preview ? "secondary" : "ghost"}
                      onClick={() => setPreview(true)}
                    >
                      Preview
                    </Button>
                  </div>
                </div>
                {preview ? (
                  <div className="prose-card min-h-24 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3">
                    {renderMarkdown(draft.description) ?? (
                      <span className="text-xs text-[var(--muted-foreground)]">No description</span>
                    )}
                  </div>
                ) : (
                  <Textarea
                    aria-label="Card description (Markdown)"
                    value={draft.description}
                    onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                    placeholder="Markdown supported"
                  />
                )}
              </div>

              <div className="flex flex-col gap-2">
                <Field label="Priority" htmlFor="card-priority">
                  <Select
                    id="card-priority"
                    value={draft.priority}
                    onChange={(event) =>
                      setDraft({ ...draft, priority: event.target.value as Priority })
                    }
                  >
                    {PRIORITIES.map((priority) => (
                      <option key={priority} value={priority}>
                        {priority}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Due date" htmlFor="card-due">
                  <Input
                    id="card-due"
                    type="date"
                    value={draft.due}
                    onChange={(event) => setDraft({ ...draft, due: event.target.value })}
                  />
                </Field>
                <Field label="List" htmlFor="card-list">
                  <Select
                    id="card-list"
                    value={card.list_id}
                    onChange={(event) => moveMutation.mutate(event.target.value)}
                  >
                    {lists.map((list) => (
                      <option key={list.id} value={list.id}>
                        {list.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                    Labels
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {labelOptions.length === 0 ? (
                      <span className="text-xs text-[var(--muted-foreground)]">
                        No labels on this board yet.
                      </span>
                    ) : (
                      labelOptions.map((label) => {
                        const selected = draft.labels.includes(label.id);
                        return (
                          <button
                            key={label.id}
                            type="button"
                            aria-pressed={selected}
                            onClick={() =>
                              setDraft({
                                ...draft,
                                labels: selected
                                  ? draft.labels.filter((id) => id !== label.id)
                                  : [...draft.labels, label.id],
                              })
                            }
                            className={selected ? "opacity-100" : "opacity-45"}
                          >
                            <LabelChip name={label.name} color={label.color} />
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-y border-[var(--border)] py-3">
              <Button variant="secondary" size="sm" onClick={save} disabled={!dirty || updateMutation.isPending}>
                {updateMutation.isPending ? "Saving…" : "Save changes"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!card.completed_at && card.kind !== "manual" && !card.ready}
                title={
                  !card.completed_at && card.blockers.length > 0
                    ? `Blocked by ${card.blockers
                        .map((blocker) => blocker.key ?? blocker.title ?? blocker.reason)
                        .join(", ")}`
                    : undefined
                }
                onClick={() => {
                  if (!card.completed_at && card.human_action_required && onConfirmHuman) {
                    void onConfirmHuman(card.version, "").then(onClose);
                    return;
                  }
                  updateMutation.mutate({ version: card.version, completed: !card.completed_at });
                }}
              >
                <CircleCheck size={14} />
                {card.completed_at
                  ? "Mark incomplete"
                  : card.human_action_required
                    ? "Confirm human action"
                    : "Mark complete"}
              </Button>
              <Button variant="outline" size="sm" onClick={() => archiveMutation.mutate()}>
                <Archive size={14} /> Archive
              </Button>
              {card.completed_at ? (
                <Badge tone="success">Completed {formatDateTime(card.completed_at)}</Badge>
              ) : null}
            </div>

            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold">Checklists</h3>
                <form
                  className="flex gap-1.5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (checklistTitle.trim()) checklistMutation.mutate(checklistTitle.trim());
                  }}
                >
                  <Input
                    className="h-8 w-40"
                    placeholder="New checklist"
                    aria-label="New checklist title"
                    value={checklistTitle}
                    onChange={(event) => setChecklistTitle(event.target.value)}
                  />
                  <Button size="sm" type="submit" disabled={!checklistTitle.trim()}>
                    Add
                  </Button>
                </form>
              </div>
              {(card.checklists ?? []).length === 0 ? (
                <p className="text-xs text-[var(--muted-foreground)]">No checklists yet.</p>
              ) : (
                <div className="flex flex-col gap-3">
                  {(card.checklists ?? []).map((checklist) => (
                    <div key={checklist.id} className="rounded-lg border border-[var(--border)] p-2.5">
                      <div className="mb-1.5 flex items-center gap-2">
                        <CheckSquare size={14} className="text-[var(--muted-foreground)]" />
                        <span className="text-xs font-semibold">{checklist.title}</span>
                        <span className="text-[11px] text-[var(--muted-foreground)]">
                          {checklist.items.filter((item) => item.completed).length}/
                          {checklist.items.length}
                        </span>
                      </div>
                      <ul className="flex flex-col gap-1">
                        {checklist.items.map((item) => (
                          <li key={item.id} className="flex items-center gap-2">
                            <button
                              type="button"
                              aria-pressed={item.completed}
                              aria-label={`${item.completed ? "Uncheck" : "Check"} ${item.text}`}
                              onClick={() => toggleItemMutation.mutate(item)}
                              className="text-[var(--muted-foreground)] hover:text-[var(--success)]"
                            >
                              {item.completed ? <CircleCheck size={14} /> : <Circle size={14} />}
                            </button>
                            <span
                              className={
                                item.completed
                                  ? "text-xs text-[var(--muted-foreground)] line-through"
                                  : "text-xs"
                              }
                            >
                              {item.text}
                            </span>
                          </li>
                        ))}
                      </ul>
                      <form
                        className="mt-1.5 flex gap-1.5"
                        onSubmit={(event) => {
                          event.preventDefault();
                          const text = (itemText[checklist.id] ?? "").trim();
                          if (text) itemMutation.mutate({ checklistId: checklist.id, text });
                        }}
                      >
                        <Input
                          className="h-7 text-xs"
                          placeholder="Add item"
                          aria-label={`Add item to ${checklist.title}`}
                          value={itemText[checklist.id] ?? ""}
                          onChange={(event) =>
                            setItemText((current) => ({
                              ...current,
                              [checklist.id]: event.target.value,
                            }))
                          }
                        />
                        <Button size="sm" variant="ghost" type="submit">
                          Add
                        </Button>
                      </form>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section>
              <div className="mb-2 flex items-center gap-2">
                <h3 className="text-sm font-semibold">Comments</h3>
                {live ? (
                  <Badge tone="success" className="align-middle">
                    live
                  </Badge>
                ) : null}
              </div>
              {(mentionsQuery.data ?? []).length > 0 ? (
                <ul aria-label="Agent mentions" className="mb-2 flex flex-col gap-1">
                  {(mentionsQuery.data ?? []).map((job) => (
                    <li
                      key={job.id}
                      className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs"
                    >
                      <Bot size={14} className="text-[var(--muted-foreground)]" />
                      <span className="font-medium">{job.agent_name}</span>
                      <Badge tone={MENTION_TONES[job.status]}>{job.status}</Badge>
                      {job.error ? (
                        <span
                          className="max-w-[220px] truncate text-[var(--destructive)]"
                          title={job.error}
                        >
                          {job.error}
                        </span>
                      ) : null}
                      {job.can_retry ? (
                        <Button
                          size="sm"
                          variant="outline"
                          className="ml-auto"
                          disabled={retryMentionMutation.isPending}
                          onClick={() => retryMentionMutation.mutate(job.id)}
                        >
                          Retry
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              <ul className="flex flex-col gap-2">
                {(card.comments ?? []).map((entry) => (
                  <li key={entry.id} className="rounded-lg border border-[var(--border)] p-2.5">
                    <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                      <span className="font-medium text-[var(--foreground)]">
                        {entry.actor_name ?? "Unknown"}
                      </span>
                      <Badge tone={entry.actor_type === "agent" ? "brand" : "neutral"}>
                        {entry.actor_type ?? "user"}
                      </Badge>
                      <span>{formatDateTime(entry.created_at)}</span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-sm">{entry.content}</p>
                  </li>
                ))}
                {(card.comments ?? []).length === 0 ? (
                  <li className="text-xs text-[var(--muted-foreground)]">No comments yet.</li>
                ) : null}
              </ul>
              <form
                className="mt-2 flex items-end gap-1.5"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (comment.trim()) commentMutation.mutate(comment.trim());
                }}
              >
                <div className="relative flex-1">
                  <Textarea
                    ref={commentField}
                    id="new-comment"
                    className="min-h-16"
                    placeholder="Add a comment — type @ to mention an agent"
                    aria-label="New comment"
                    aria-autocomplete="list"
                    aria-controls="mention-suggestions"
                    aria-expanded={suggestions.length > 0}
                    value={comment}
                    onChange={(event) => {
                      const value = event.target.value;
                      setComment(value);
                      setMentionToken(activeMention(value, event.target.selectionStart));
                      setMentionIndex(0);
                    }}
                    onKeyDown={(event) => {
                      if (suggestions.length === 0) return;
                      if (event.key === "ArrowDown") {
                        event.preventDefault();
                        setMentionIndex((current) => (current + 1) % suggestions.length);
                      } else if (event.key === "ArrowUp") {
                        event.preventDefault();
                        setMentionIndex(
                          (current) =>
                            (current - 1 + suggestions.length) % suggestions.length,
                        );
                      } else if (event.key === "Enter") {
                        event.preventDefault();
                        const highlighted = suggestions[mentionIndex];
                        if (highlighted) chooseAgent(highlighted);
                      }
                    }}
                    onBlur={() => setMentionToken(null)}
                  />
                  {suggestions.length > 0 ? (
                    <div
                      id="mention-suggestions"
                      role="listbox"
                      aria-label="Mention an agent"
                      className="absolute bottom-full left-0 z-10 mb-1 w-72 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-lg"
                    >
                      {suggestions.map((agent, index) => (
                        <button
                          key={agent.id}
                          type="button"
                          role="option"
                          aria-selected={index === mentionIndex}
                          onMouseDown={(event) => {
                            event.preventDefault();
                            chooseAgent(agent);
                          }}
                          className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs ${
                            index === mentionIndex
                              ? "bg-[var(--surface-raised)] text-[var(--foreground)]"
                              : "text-[var(--muted-foreground)]"
                          }`}
                        >
                          <Bot size={14} />
                          <span className="font-medium">{agent.name}</span>
                          <span className="ml-auto text-[11px]">
                            {agent.role_template_name ?? "no role"}
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
                <Button type="submit" size="icon" aria-label="Send comment" disabled={!comment.trim()}>
                  <Send size={14} />
                </Button>
              </form>
            </section>

            <section>
              <h3 className="mb-2 text-sm font-semibold">History</h3>
              <ul className="flex flex-col gap-1 text-xs text-[var(--muted-foreground)]">
                {(activityQuery.data ?? []).slice(0, 12).map((entry) => (
                  <li key={entry.id} className="flex gap-2">
                    <Badge tone={entry.actor_type === "agent" ? "brand" : "neutral"}>
                      {entry.actor_type}
                    </Badge>
                    <span className="text-[var(--foreground)]">{entry.action}</span>
                    <span className="ml-auto">{formatDateTime(entry.timestamp)}</span>
                  </li>
                ))}
                {(activityQuery.data ?? []).length === 0 ? (
                  <li>No history yet.</li>
                ) : null}
              </ul>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
