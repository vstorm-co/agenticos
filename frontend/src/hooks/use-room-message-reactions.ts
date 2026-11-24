"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useRoomIdentity } from "@/hooks/use-room";
import { announceRoomChange } from "@/lib/room-events";
import {
  removeRoomMessageReaction,
  setRoomMessageReaction,
} from "@/lib/room-message-reactions-api";
import type { RoomMessageReactionSummary } from "@/types/room-message-reaction";

type ReactionIntent = { action: "add" | "remove"; emoji: string };

export function useRoomMessageReactions(
  conversationId: string | null,
  messageId: string | null,
  initialReactions: RoomMessageReactionSummary[] | undefined,
) {
  const identity = useRoomIdentity();
  const { accountId, organizationId, tenant, current } = identity;
  const [reactions, setReactions] = useState<RoomMessageReactionSummary[]>(initialReactions ?? []);
  const [isPending, setPending] = useState(false);
  const [hasError, setError] = useState(false);
  const [failedIntent, setFailedIntent] = useState<ReactionIntent | null>(null);
  const scopeKey = JSON.stringify([accountId, organizationId, tenant, conversationId, messageId]);
  const activeScope = useRef(scopeKey);
  const inFlight = useRef<symbol | null>(null);

  // A mounted message component can receive a different message without
  // unmounting. Invalidate old requests during commit, before their promises can
  // update the new message's local reaction state.
  useLayoutEffect(() => {
    if (activeScope.current === scopeKey) return;
    activeScope.current = scopeKey;
    inFlight.current = null;
    setReactions(initialReactions ?? []);
    setPending(false);
    setError(false);
    setFailedIntent(null);
  }, [conversationId, initialReactions, messageId, scopeKey]);

  useEffect(() => {
    if (activeScope.current === scopeKey) setReactions(initialReactions ?? []);
  }, [initialReactions, scopeKey]);

  const change = useCallback(
    async (intent: ReactionIntent): Promise<boolean> => {
      if (
        conversationId === null ||
        messageId === null ||
        accountId === undefined ||
        organizationId === null ||
        !current() ||
        activeScope.current !== scopeKey ||
        inFlight.current !== null
      ) {
        return false;
      }
      const requestId = Symbol();
      inFlight.current = requestId;
      setPending(true);
      setError(false);
      setFailedIntent(null);
      const stillCurrent = () =>
        current() && activeScope.current === scopeKey && inFlight.current === requestId;
      try {
        const result =
          intent.action === "add"
            ? await setRoomMessageReaction(conversationId, messageId, intent.emoji)
            : await removeRoomMessageReaction(conversationId, messageId, intent.emoji);
        if (!stillCurrent()) return false;
        setReactions(result.reactions);
        setFailedIntent(null);
        announceRoomChange({ conversationId, accountId, organizationId });
        return true;
      } catch {
        if (!stillCurrent()) return false;
        setError(true);
        setFailedIntent(intent);
        return false;
      } finally {
        if (inFlight.current === requestId) {
          inFlight.current = null;
          if (current() && activeScope.current === scopeKey) setPending(false);
        }
      }
    },
    [accountId, conversationId, current, messageId, organizationId, scopeKey],
  );

  const add = useCallback((emoji: string) => change({ action: "add", emoji }), [change]);
  const remove = useCallback((emoji: string) => change({ action: "remove", emoji }), [change]);
  const retry = useCallback(
    () => (failedIntent ? change(failedIntent) : Promise.resolve(false)),
    [change, failedIntent],
  );

  return { reactions, add, remove, retry, isPending, hasError };
}
