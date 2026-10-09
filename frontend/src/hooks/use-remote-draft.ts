"use client";

import { useEffect, useRef, useState } from "react";

import { onRemoteChange } from "@/lib/live-updates";
import { useAuthStore } from "@/stores";
import type { ChangeEvent, ChangeResource } from "@/types/change-events";

interface RemoteDraftOptions<T> {
  resource: ChangeResource;
  id: string;
  /** What is being edited here, or null before it was adopted. */
  local: T | null;
  /** The stored version the server last answered with. */
  stored: T | null | undefined;
  /** When `stored` was last answered for - see `useAgent`'s `fetchedAt`. */
  fetchedAt: number;
  adopt: (stored: T) => void;
}

interface RemoteDraft {
  /** True while a change made elsewhere is being fetched or awaits a decision:
   *  saving the local draft now would overwrite it unseen. */
  held: boolean;
  /** A change made elsewhere to a draft with unsaved edits here. */
  conflict: ChangeEvent | null;
  /** Take the stored version, dropping the edits made here. */
  reload: () => void;
  /** Keep the edits made here; the next save overwrites the other change. */
  keepMine: () => void;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * Keep an editor that saves on its own from overwriting a change made elsewhere
 * (#2061).
 *
 * When the live-update socket says this row changed - through the API, MCP, the
 * assistant or somebody else's console - saving waits for the refetch that
 * event started. If the stored version moved and nothing was edited here, the
 * editor adopts it silently; if there were edits, it shows `conflict` and keeps
 * holding until the person chooses. The reader's own console saves are echoes
 * of what this tab already has, and are not changes "elsewhere".
 */
export function useRemoteDraft<T>({
  resource,
  id,
  local,
  stored,
  fetchedAt,
  adopt,
}: RemoteDraftOptions<T>): RemoteDraft {
  const me = useAuthStore((state) => state.user?.id);
  const [waiting, setWaiting] = useState<{
    event: ChangeEvent;
    since: number;
    stored: string;
    edited: boolean;
  } | null>(null);
  const [conflict, setConflict] = useState<ChangeEvent | null>(null);
  // Read when an event arrives rather than subscribed to, so typing does not
  // re-register the listener on every keystroke.
  const current = useRef({ local, stored, fetchedAt });
  useEffect(() => {
    current.current = { local, stored, fetchedAt };
  }, [local, stored, fetchedAt]);

  useEffect(
    () =>
      onRemoteChange((event) => {
        if (event.resource !== resource || event.id !== id) return;
        if (event.surface === "console" && event.actor_user_id === me) return;
        const now = current.current;
        setWaiting({
          event,
          since: now.fetchedAt,
          stored: JSON.stringify(now.stored),
          edited: now.local !== null && !same(now.local, now.stored),
        });
      }),
    [resource, id, me],
  );

  // Settled during render, the way the Builder adopts its first draft: the
  // refetch has answered, so whether anything moved is known now, and an effect
  // would paint one frame of the stale decision first.
  if (waiting !== null && fetchedAt > waiting.since) {
    setWaiting(null);
    if (stored != null && JSON.stringify(stored) !== waiting.stored) {
      if (waiting.edited) setConflict(waiting.event);
      else adopt(stored);
    }
  }

  return {
    held: waiting !== null || conflict !== null,
    conflict,
    reload: () => {
      setConflict(null);
      if (stored != null) adopt(stored);
    },
    keepMine: () => setConflict(null),
  };
}
