import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { activeMention, applyMention, matchingAgents, type MentionToken } from "@/lib/mentions";
import { keys } from "@/lib/queries";
import type { AgentDirectoryEntry } from "@/lib/types";

/**
 * The card's comment composer with @-mention suggestions, and the agent mention jobs it starts.
 * Called by the dialog, so an unsent comment lives as long as the dialog does.
 */
export function useCardComments({
  boardId,
  loopId,
  cardId,
  refresh,
  onError,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  refresh: () => void;
  onError: (error: unknown) => void;
}) {
  const queryClient = useQueryClient();
  const agentsQuery = useQuery({
    queryKey: keys.agentDirectory,
    queryFn: () => api.listAgentDirectory(),
  });
  const mentionsQuery = useQuery({
    queryKey: keys.mentions(boardId, loopId, cardId),
    queryFn: () => api.listMentions(boardId, loopId, cardId),
  });
  const [comment, setComment] = useState("");
  const [mentionToken, setMentionToken] = useState<MentionToken | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const commentField = useRef<HTMLTextAreaElement | null>(null);

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
      mentionToken ? matchingAgents(agentsQuery.data ?? [], mentionToken.query).slice(0, 6) : [],
    [mentionToken, agentsQuery.data],
  );

  function changeComment(value: string, caret: number) {
    setComment(value);
    setMentionToken(activeMention(value, caret));
    setMentionIndex(0);
  }

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

  return {
    mentions: mentionsQuery.data ?? [],
    retryMention: retryMentionMutation,
    comment,
    changeComment,
    closeSuggestions: () => {
      setMentionToken(null);
    },
    suggestions,
    mentionIndex,
    setMentionIndex,
    chooseAgent,
    commentField,
    addComment: commentMutation,
  };
}
