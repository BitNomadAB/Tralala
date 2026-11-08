import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { controlledText, type RunAction, type TalkRequest } from "./discussionRules";

/** One round, as "Ask again" starts it, or the rounds "Let them talk it out" asks for. */
type StartRequest = { rounds: 1 } | TalkRequest;

/**
 * The runs of one discussion as a person starts and steers them: one round after a reply, "Let
 * them talk it out" with its dialog, and Pause, Resume and Stop on the run under way. Every call
 * refreshes the thread; the view tells what happened from the thread and its events.
 */
export function useDiscussionRuns(boardId: string, discussionId: string, refresh: () => void) {
  const toast = useToast();
  const [talkOpen, setTalkOpen] = useState(false);

  const start = useMutation({
    mutationFn: (input: StartRequest) => api.startDiscussion(boardId, discussionId, input),
    onSuccess: () => {
      setTalkOpen(false);
      refresh();
    },
    onError: (error, input) => {
      refresh();
      toast.push({
        title: "autonomous" in input ? "Could not start the run" : "Could not start the round",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const control = useMutation({
    mutationFn: (input: { runId: string; action: RunAction }) =>
      api.controlDiscussionRun(boardId, discussionId, input.runId, input.action),
    onSuccess: (_summary, input) => {
      refresh();
      toast.push({ title: controlledText(input.action), variant: "success" });
    },
    onError: (error) => {
      refresh();
      toast.push({
        title: "Could not change the run",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return {
    talkOpen,
    setTalkOpen,
    /** One round, for a reply the server does not answer by itself. */
    askRound: () => {
      start.mutate({ rounds: 1 });
    },
    talk: (request: TalkRequest) => {
      start.mutate(request);
    },
    starting: start.isPending,
    control: (runId: string, action: RunAction) => {
      control.mutate({ runId, action });
    },
    controlling: control.isPending,
  };
}

export type DiscussionRuns = ReturnType<typeof useDiscussionRuns>;
