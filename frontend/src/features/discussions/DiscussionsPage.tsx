import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, MessagesSquare, Plus, Send } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { keys, useAgents } from "@/lib/queries";
import { formatDateTime } from "@/lib/utils";
import { RunPanel } from "./RunPanel";
import { useDiscussionEvents } from "./useDiscussionEvents";

const MODES = [
  { value: "manual", label: "Manual — mention @agents or start a run" },
  { value: "roundtable", label: "Roundtable — every human message starts one round" },
  { value: "autonomous", label: "Autonomous — messages start rounds; runs may loop" },
];

export function DiscussionsPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: agents = [] } = useAgents();
  const [boardId, setBoardId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [dialogBoardId, setDialogBoardId] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [goal, setGoal] = useState("");
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState("manual");
  const [participants, setParticipants] = useState<string[]>([]);
  const [reply, setReply] = useState("");
  const [reviewing, setReviewing] = useState<null | { decision: "approve" | "veto" | "rework" }>(
    null,
  );
  const [reason, setReason] = useState("");

  const activeBoard = boardId;

  const boardsQuery = useQuery({
    queryKey: keys.discussionBoards,
    queryFn: () => api.listDiscussionBoards(),
    // Keep the ordering fresh while the board list is open; a selected board refreshes on demand.
    refetchInterval: activeBoard ? false : 30_000,
  });
  const boards = boardsQuery.data ?? [];
  const activeBoardEntry = boards.find((entry) => entry.board_id === activeBoard) ?? null;
  const dialogBoardEntry = boards.find((entry) => entry.board_id === dialogBoardId) ?? null;

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.discussions(activeBoard) });
    if (selectedId) {
      void queryClient.invalidateQueries({ queryKey: ["discussion", activeBoard, selectedId] });
    }
  }, [queryClient, activeBoard, selectedId]);

  const backToBoards = useCallback(() => {
    // The overview is one query for every board; refresh it when the list becomes visible instead
    // of on every thread event.
    void queryClient.invalidateQueries({ queryKey: keys.discussionBoards });
    setBoardId("");
    setSelectedId(null);
  }, [queryClient]);

  const live = useDiscussionEvents(activeBoard, selectedId, invalidate);

  const discussionsQuery = useQuery({
    queryKey: keys.discussions(activeBoard),
    queryFn: () => api.listDiscussions(activeBoard),
    enabled: Boolean(activeBoard),
  });
  const discussions = discussionsQuery.data ?? [];
  const ticketsQuery = useQuery({
    queryKey: ["discussion-tickets", dialogBoardId],
    queryFn: () => api.listBoardTickets(dialogBoardId, { limit: 200 }),
    enabled: Boolean(dialogBoardId) && creating,
  });
  const detailQuery = useQuery({
    queryKey: ["discussion", activeBoard, selectedId],
    queryFn: () => api.getDiscussion(activeBoard, String(selectedId)),
    enabled: Boolean(activeBoard && selectedId),
    refetchInterval: (query) => (query.state.data?.run_state === "running" && !live ? 1500 : false),
  });

  const selected = detailQuery.data ?? discussions.find((item) => item.id === selectedId) ?? null;

  const createMutation = useMutation({
    mutationFn: () =>
      api.createDiscussion(dialogBoardId, {
        card_id: ticketId,
        goal: goal.trim(),
        mode,
        participant_ids: participants,
        ...(title.trim() ? { title: title.trim() } : {}),
      }),
    onSuccess: (discussion) => {
      setCreating(false);
      setTicketId("");
      setGoal("");
      setTitle("");
      setParticipants([]);
      // The dialog can name a board other than the one being viewed, so follow the thread there.
      const target = dialogBoardId;
      void queryClient.invalidateQueries({ queryKey: keys.discussions(target) });
      void queryClient.invalidateQueries({ queryKey: ["discussion-tickets", target] });
      void queryClient.invalidateQueries({ queryKey: keys.discussionBoards });
      setBoardId(target);
      setSelectedId(discussion.id);
      toast.push({ title: "Discussion created", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not create discussion",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: (input: { decision: "approve" | "veto" | "rework"; reason: string }) =>
      api.reviewDiscussion(activeBoard, String(selectedId), input),
    onSuccess: (discussion) => {
      setReviewing(null);
      setReason("");
      invalidate();
      toast.push({ title: `Discussion ${discussion.status}`, variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not record the decision",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const replyMutation = useMutation({
    mutationFn: () =>
      api.postDiscussionMessage(activeBoard, String(selectedId), { content: reply.trim() }),
    onSuccess: (discussion) => {
      setReply("");
      invalidate();
      if (discussion.auto_run === "already_running") {
        toast.push({
          title: "A run is already active",
          description: "Your message is saved and joins the conversation; no second run starts.",
          variant: "info",
        });
      } else if (discussion.auto_run === "thread_closed") {
        toast.push({
          title: "The discussion is closed",
          description: "The message is saved, but a closed thread does not start a run.",
          variant: "warning",
        });
      } else if (discussion.auto_run === "no_participants") {
        toast.push({
          title: "No AI participants",
          description: "The message is saved; add participants before agents can answer.",
          variant: "warning",
        });
      }
    },
    onError: (error) => {
      toast.push({
        title: "Could not post message",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const boardTickets = useMemo(() => ticketsQuery.data ?? [], [ticketsQuery.data]);

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div>
          <h1 className="text-xl font-semibold">Discussions</h1>
          <p className="text-xs text-[var(--muted-foreground)]">
            Ticket-bound threads with human and AI participants. Discussion never executes changes.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button
            onClick={() => {
              // Open with the board being viewed, so the common case needs no extra click; the
              // dialog still lists every board, because a thread may belong somewhere else and
              // because a board with no Tickets yet cannot host one.
              setDialogBoardId(activeBoard);
              setTicketId("");
              setCreating(true);
            }}
          >
            <Plus size={15} /> New discussion
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <div className="card-surface max-h-[70vh] overflow-y-auto p-2">
          {activeBoard ? (
            <>
              <div className="flex items-center gap-1.5 border-b border-[var(--border)] px-1 pb-2">
                <Button size="sm" variant="ghost" onClick={backToBoards}>
                  <ChevronLeft size={14} /> All boards
                </Button>
                <span className="truncate text-xs font-semibold">
                  {activeBoardEntry?.board_name ?? "Board"}
                </span>
              </div>
              {discussionsQuery.isLoading ? (
                <p className="p-3 text-xs text-[var(--muted-foreground)]">Loading discussions…</p>
              ) : discussions.length === 0 ? (
                <p className="p-3 text-xs text-[var(--muted-foreground)]">
                  No discussions yet. Reference an existing ticket to start one.
                </p>
              ) : (
                <ul className="flex flex-col gap-1 pt-1">
                  {discussions.map((discussion) => (
                    <li key={discussion.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(discussion.id)}
                        className={`w-full rounded-lg p-2.5 text-left hover:bg-[var(--surface-raised)] ${
                          selectedId === discussion.id ? "bg-[var(--surface-raised)]" : ""
                        }`}
                      >
                        <p className="flex items-center gap-1.5 text-sm font-medium">
                          <MessagesSquare size={14} className="text-[var(--muted-foreground)]" />
                          <span className="truncate">{discussion.title}</span>
                        </p>
                        <p className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                          {discussion.card_title ?? discussion.card_id}
                          {discussion.loop_name ? ` · ${discussion.loop_name}` : ""} ·{" "}
                          {discussion.message_count} messages · {discussion.participant_count}{" "}
                          agents
                        </p>
                        <p className="mt-1 flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
                          <Badge tone={discussion.status === "open" ? "neutral" : "brand"}>
                            {discussion.status}
                          </Badge>
                          {formatDateTime(discussion.last_activity_at)}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : boardsQuery.isLoading ? (
            <p className="p-3 text-xs text-[var(--muted-foreground)]">Loading boards…</p>
          ) : boards.length === 0 ? (
            <p className="p-3 text-xs text-[var(--muted-foreground)]">
              No boards yet. Create a board to start a discussion.
            </p>
          ) : (
            <>
              <p className="px-2 pb-2 pt-1 text-[11px] text-[var(--muted-foreground)]">
                Boards by newest discussion activity.
              </p>
              <ul aria-label="Boards with discussions" className="flex flex-col gap-1">
                {boards.map((entry) => (
                  <li key={entry.board_id}>
                    <button
                      type="button"
                      aria-label={`Open discussions for ${entry.board_name}`}
                      onClick={() => {
                        setBoardId(entry.board_id);
                        setSelectedId(null);
                      }}
                      className="w-full rounded-lg p-2.5 text-left hover:bg-[var(--surface-raised)]"
                    >
                      <p className="flex items-center gap-1.5 text-sm font-medium">
                        <MessagesSquare size={14} className="text-[var(--muted-foreground)]" />
                        <span className="truncate">{entry.board_name}</span>
                        {entry.status !== "active" ? (
                          <Badge tone="warning">{entry.status}</Badge>
                        ) : null}
                      </p>
                      <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                        {entry.discussion_count === 0
                          ? "No discussions yet"
                          : `${entry.discussion_count} discussion${
                              entry.discussion_count === 1 ? "" : "s"
                            } · ${entry.open_count} open`}
                      </p>
                      <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                        {entry.last_activity_at
                          ? `Last activity ${formatDateTime(entry.last_activity_at)}`
                          : "Waiting for the first thread"}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <div className="card-surface flex max-h-[70vh] min-h-[320px] flex-col p-4">
          {!activeBoard ? (
            <p className="m-auto text-sm text-[var(--muted-foreground)]">
              Select a board to see its most recently active discussions.
            </p>
          ) : !selected ? (
            <p className="m-auto text-sm text-[var(--muted-foreground)]">
              Select a discussion to read the thread.
            </p>
          ) : (
            <>
              <div className="border-b border-[var(--border)] pb-2">
                <h2 className="text-sm font-semibold">
                  {selected.title}
                  {live ? (
                    <Badge tone="success" className="ml-2 align-middle">
                      live
                    </Badge>
                  ) : null}
                </h2>
                <p className="text-[11px] text-[var(--muted-foreground)]">
                  {selected.mode} · created by {selected.created_by_name} ·{" "}
                  {selected.participants.length} snapshot(s)
                </p>
                {selected.loop_id ? (
                  <p className="mt-1 text-[11px]">
                    <Link
                      to={`/boards/${activeBoard}/loops/${selected.loop_id}?card=${selected.card_id}`}
                      className="text-[var(--brand)] underline"
                    >
                      Open {selected.ticket_key ?? selected.card_title ?? "ticket"}
                    </Link>
                    <span className="text-[var(--muted-foreground)]">
                      {" "}
                      in {selected.loop_name ?? "its Loop"}
                    </span>
                  </p>
                ) : null}
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  {selected.participants
                    .map(
                      (participant) =>
                        `${participant.display_name} (${participant.role_template_name ?? "no role"})`,
                    )
                    .join(" · ") || "No AI participants yet"}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      ["approved", "vetoed", "cancelled"].includes(selected.status) ||
                      ["running", "paused"].includes(selected.run_state)
                    }
                    onClick={() => setReviewing({ decision: "approve" })}
                  >
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={
                      ["approved", "vetoed", "cancelled"].includes(selected.status) ||
                      ["running", "paused"].includes(selected.run_state)
                    }
                    onClick={() => setReviewing({ decision: "rework" })}
                  >
                    Request rework
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={
                      ["approved", "vetoed", "cancelled"].includes(selected.status) ||
                      ["running", "paused"].includes(selected.run_state)
                    }
                    onClick={() => setReviewing({ decision: "veto" })}
                  >
                    Veto
                  </Button>
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    Each agent answers with its snapshotted role and an explicit verdict.
                  </span>
                </div>
                <RunPanel boardId={activeBoard} discussion={selected} onChanged={invalidate} />
                {(selected.votes ?? []).length > 0 ? (
                  <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                    {(selected.votes ?? []).map((vote) => (
                      <li
                        key={`${vote.participant_id}-${vote.created_at}`}
                        className="rounded-md border border-[var(--border)] px-1.5 py-0.5"
                      >
                        {vote.display_name ?? "agent"}:{" "}
                        <span className="font-medium">{vote.position}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <ul className="scrollbar-thin flex-1 overflow-y-auto py-2">
                {selected.messages.map((message) => (
                  <li key={message.id} className="mb-3">
                    <p className="text-[11px] text-[var(--muted-foreground)]">
                      <span className="font-medium text-[var(--foreground)]">
                        {message.author_name}
                      </span>{" "}
                      · {message.author_type} · {formatDateTime(message.created_at)}
                    </p>
                    <p className="mt-0.5 whitespace-pre-wrap text-sm">{message.content}</p>
                  </li>
                ))}
              </ul>
              <form
                className="flex items-end gap-2 border-t border-[var(--border)] pt-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (reply.trim()) replyMutation.mutate();
                }}
              >
                <Textarea
                  aria-label="Reply"
                  className="min-h-10 flex-1"
                  value={reply}
                  onChange={(event) => setReply(event.target.value)}
                  placeholder={
                    ["roundtable", "autonomous"].includes(selected.mode)
                      ? "Reply — the participants answer automatically"
                      : "Reply — mention @agents to make the participants answer"
                  }
                />
                <Button type="submit" disabled={!reply.trim() || replyMutation.isPending}>
                  <Send size={14} /> Send
                </Button>
              </form>
              {selected.mode === "manual" ? (
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  Mention <span className="font-medium text-[var(--foreground)]">@agents</span> (or
                  a participant&apos;s name) to make the thread answer, or start a run above.
                </p>
              ) : null}
            </>
          )}
        </div>
      </div>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent
          title="New discussion"
          description="Pick the board, then one of its tickets. Every discussion references exactly one existing ticket."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (ticketId && goal.trim()) createMutation.mutate();
            }}
          >
            <Field
              label="Board"
              htmlFor="discussion-board"
              hint="A thread belongs to one board. Boards are listed with their ticket count, because a board without tickets cannot host a discussion yet."
            >
              <Select
                id="discussion-board"
                value={dialogBoardId}
                onChange={(event) => {
                  setDialogBoardId(event.target.value);
                  setTicketId("");
                }}
                required
              >
                <option value="">Select a board…</option>
                {boards.map((entry) => (
                  <option key={entry.board_id} value={entry.board_id}>
                    {entry.board_name} · {entry.ticket_count}{" "}
                    {entry.ticket_count === 1 ? "ticket" : "tickets"}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Ticket" htmlFor="discussion-ticket">
              <Select
                id="discussion-ticket"
                value={ticketId}
                onChange={(event) => setTicketId(event.target.value)}
                disabled={!dialogBoardId || boardTickets.length === 0}
                required
              >
                <option value="">Select a ticket…</option>
                {boardTickets.map((card) => (
                  <option key={card.id} value={card.id}>
                    {card.title} · {card.loop_name}
                  </option>
                ))}
              </Select>
            </Field>
            {ticketsQuery.isLoading ? (
              <p className="text-xs text-[var(--muted-foreground)]">Loading tickets…</p>
            ) : dialogBoardId && boardTickets.length === 0 ? (
              <p className="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted-foreground)]">
                {dialogBoardEntry?.board_name ?? "This board"} has no tickets yet, and a discussion
                must reference one. Open{" "}
                <Link className="underline" to={`/boards/${dialogBoardId}`}>
                  {dialogBoardEntry?.board_name ?? "the board"}
                </Link>{" "}
                and add a ticket to a Loop, or pick another board above.
              </p>
            ) : null}
            <Field label="Title (optional)" htmlFor="discussion-title">
              <Input
                id="discussion-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={200}
              />
            </Field>
            <Field label="Goal or question" htmlFor="discussion-goal">
              <Textarea
                id="discussion-goal"
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                required
                maxLength={20000}
              />
            </Field>
            <Field label="Mode" htmlFor="discussion-mode">
              <Select
                id="discussion-mode"
                value={mode}
                onChange={(event) => setMode(event.target.value)}
              >
                {MODES.map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </Select>
            </Field>
            <fieldset className="flex flex-col gap-1.5">
              <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                Participants
              </legend>
              {agents.length === 0 ? (
                <p className="text-xs text-[var(--muted-foreground)]">
                  No enabled agents yet. Create one in Settings → AI agents.
                </p>
              ) : (
                agents.map((agent) => (
                  <label key={agent.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={participants.includes(agent.id)}
                      onChange={(event) =>
                        setParticipants((current) =>
                          event.target.checked
                            ? [...current, agent.id]
                            : current.filter((id) => id !== agent.id),
                        )
                      }
                    />
                    {agent.name}
                    <span className="text-[11px] text-[var(--muted-foreground)]">
                      {agent.role_template_name ?? "no role"}
                    </span>
                  </label>
                ))
              )}
            </fieldset>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!ticketId || !goal.trim() || createMutation.isPending}
              >
                {createMutation.isPending ? "Creating…" : "Create discussion"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={reviewing !== null} onOpenChange={(open) => !open && setReviewing(null)}>
        <DialogContent
          title={
            reviewing?.decision === "approve"
              ? "Approve outcome"
              : reviewing?.decision === "veto"
                ? "Veto outcome"
                : "Request rework"
          }
          description="Approval records a decision only — it never changes the ticket. Veto and rework require an explanation."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!reviewing) return;
              if (reviewing.decision === "approve" || reason.trim()) {
                reviewMutation.mutate({ decision: reviewing.decision, reason: reason.trim() });
              }
            }}
          >
            <Field
              label={reviewing?.decision === "approve" ? "Note (optional)" : "Explanation"}
              htmlFor="review-reason"
            >
              <Textarea
                id="review-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                required={reviewing?.decision !== "approve"}
                maxLength={20000}
              />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setReviewing(null)}>
                Cancel
              </Button>
              <Button
                type="submit"
                variant={reviewing?.decision === "approve" ? "primary" : "danger"}
                disabled={
                  reviewMutation.isPending || (reviewing?.decision !== "approve" && !reason.trim())
                }
              >
                Confirm
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
