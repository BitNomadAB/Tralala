import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Agent, DiscussionBoard } from "@/lib/types";

const MODES = [
  { value: "manual", label: "Manual — mention @agents or start a run" },
  { value: "roundtable", label: "Roundtable — every human message starts one round" },
  { value: "autonomous", label: "Autonomous — messages start rounds; runs may loop" },
];

/**
 * The "New discussion" button and its dialog. A thread references exactly one existing ticket, so
 * the dialog picks the board first and then one of its tickets.
 */
export function NewDiscussionDialog({
  activeBoardId,
  boards,
  agents,
  onCreated,
}: {
  activeBoardId: string;
  boards: DiscussionBoard[];
  agents: Agent[];
  onCreated: (boardId: string, discussionId: string) => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [dialogBoardId, setDialogBoardId] = useState("");
  const [ticketId, setTicketId] = useState("");
  const [goal, setGoal] = useState("");
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState("manual");
  const [participants, setParticipants] = useState<string[]>([]);
  const dialogBoardEntry = boards.find((entry) => entry.board_id === dialogBoardId) ?? null;

  const ticketsQuery = useQuery({
    queryKey: ["discussion-tickets", dialogBoardId],
    queryFn: () => api.listBoardTickets(dialogBoardId, { limit: 200 }),
    enabled: Boolean(dialogBoardId) && creating,
  });
  const boardTickets = useMemo(() => ticketsQuery.data ?? [], [ticketsQuery.data]);

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
      onCreated(target, discussion.id);
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

  return (
    <>
      <Button
        onClick={() => {
          // Open with the board being viewed, so the common case needs no extra click; the
          // dialog still lists every board, because a thread may belong somewhere else and
          // because a board with no Tickets yet cannot host one.
          setDialogBoardId(activeBoardId);
          setTicketId("");
          setCreating(true);
        }}
      >
        <Plus size={15} /> New discussion
      </Button>
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
    </>
  );
}
