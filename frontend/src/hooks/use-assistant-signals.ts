"use client";

import { useEffect, useRef, useState } from "react";

import { useAgents, useApprovals, usePermissions, useRuns } from "@/hooks";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";

/** How often the page is looked at for a form somebody is stuck in. */
const LOOK_EVERY_MS = 5000;
/** How long a form stays open, unfinished, before the Architect offers help. */
export const STUCK_AFTER_MS = 60_000;
/** How far back a failed run is still worth raising. */
const RECENT_MS = 24 * 60 * 60 * 1000;
/** The Architect's own window is a dialog too, and never a form to be stuck in. */
const ASSISTANT_WINDOW = "data-assistant-window";

export interface AssistantSignals {
  pendingApprovals: number;
  noAgents: boolean;
  /** The reader's latest failed run in the last day, if any. */
  failedRunId: string | null;
  /** The title of a form that has been open for a while, if any. */
  stuckIn: string | null;
}

/** The open dialog a person may be filling in, and what it is called. */
function openForm(): { element: Element; title: string } | null {
  const element = document.querySelector(`[role="dialog"]:not([${ASSISTANT_WINDOW}])`);
  if (element === null) return null;
  const labelledBy = element.getAttribute("aria-labelledby");
  const title =
    element.getAttribute("aria-label") ??
    (labelledBy ? document.getElementById(labelledBy)?.textContent : null) ??
    "";
  // An untitled dialog is still on a page with one.
  return { element, title: title.trim() || document.title };
}

/**
 * What the AI Architect's bubble may speak to (#2063): approvals waiting, an
 * organization with nothing in it yet, the reader's own failed run, and a form
 * they have had open, unfinished, for a minute.
 */
export function useAssistantSignals(): AssistantSignals {
  const { can } = usePermissions();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const { agents, isLoading: agentsLoading } = useAgents();
  const { total: pendingApprovals } = useApprovals({ enabled: can(Perm.approvalsDecide) });
  // Fixed for the widget's life, so the query is asked once rather than per render.
  const [since] = useState(() => new Date(Date.now() - RECENT_MS).toISOString());
  const { runs: failed } = useRuns(undefined, {
    enabled: can(Perm.runsView) && userId !== null,
    statuses: ["failed"],
    userId: userId ?? undefined,
    startedFrom: since,
  });
  const [stuckIn, setStuckIn] = useState<string | null>(null);
  const watched = useRef<{ element: Element; since: number } | null>(null);

  useEffect(() => {
    const look = () => {
      const form = openForm();
      if (form === null) {
        watched.current = null;
        setStuckIn(null);
        return;
      }
      if (watched.current?.element !== form.element) {
        watched.current = { element: form.element, since: Date.now() };
      }
      setStuckIn(Date.now() - watched.current.since >= STUCK_AFTER_MS ? form.title : null);
    };
    const timer = setInterval(look, LOOK_EVERY_MS);
    return () => clearInterval(timer);
  }, []);

  return {
    pendingApprovals,
    noAgents: !agentsLoading && agents.length === 0,
    failedRunId: failed[0]?.id ?? null,
    stuckIn,
  };
}
