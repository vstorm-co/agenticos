"use client";

import { useEffect, useRef, useState } from "react";

import { CONSOLE_TAB } from "@/lib/console-tab";
import { onRemoteChange } from "@/lib/live-updates";
import type { ChangeResource, MadeChange } from "@/types/change-events";

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
  conflict: MadeChange | null;
  /** Take the stored version, dropping the edits made here. */
  reload: () => void;
  /** Keep the edits made here; the next save overwrites the other change. */
  keepMine: () => void;
}

/**
 * Keep an editor that saves on its own from overwriting a change made elsewhere
 * (#2061).
 *
 * When the live-update socket says this row changed - through the API, MCP, the
 * assistant or somebody else's console - saving waits for the refetch that
 * event started. If the stored version moved and nothing was edited here, the
 * editor adopts it silently; if there were edits, it shows `conflict` and keeps
 * holding until the person chooses. A save made by this very tab is an echo of what
 * it already has, and is not a change "elsewhere".
 */
export function useRemoteDraft<T>({
  resource,
  id,
  local,
  stored,
  fetchedAt,
  adopt,
}: RemoteDraftOptions<T>): RemoteDraft {
  const [waiting, setWaiting] = useState<{
    event: MadeChange;
    since: number;
    stored: string;
  } | null>(null);
  const [conflict, setConflict] = useState<MadeChange | null>(null);
  // Read when an event arrives rather than subscribed to, so typing does not
  // re-register the listener on every keystroke.
  const current = useRef({ local, stored, fetchedAt });
  useEffect(() => {
    current.current = { local, stored, fetchedAt };
  }, [local, stored, fetchedAt]);

  useEffect(
    () =>
      onRemoteChange((event) => {
        // A run or the platform's own work is nobody's edit, so there is no one
        // to name in a conflict.
        if (event.surface === "run" || event.surface === "system") return;
        if (event.resource !== resource || event.id !== id) return;
        // This tab's own saves - it already has them. The same person's edit in
        // another tab is a change elsewhere like any other.
        if (event.origin_tab === CONSOLE_TAB) return;
        const now = current.current;
        setWaiting({
          event,
          since: now.fetchedAt,
          stored: JSON.stringify(now.stored),
        });
      }),
    [resource, id],
  );

  // Settled during render, the way the Builder adopts its first draft: the
  // refetch has answered, so whether anything moved is known now, and an effect
  // would paint one frame of the stale decision first.
  if (waiting !== null && fetchedAt > waiting.since) {
    setWaiting(null);
    if (stored != null && JSON.stringify(stored) !== waiting.stored) {
      // Compared now, not when the event came: typing while the refetch was in
      // flight is an edit too, and adopting would silently drop it.
      const edited = local !== null && JSON.stringify(local) !== waiting.stored;
      if (edited) setConflict(waiting.event);
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
