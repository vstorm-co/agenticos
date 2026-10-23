"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { AssistantSignals as SignalsRead } from "@/types/assistant";

/** How often the page is looked at for a form somebody is stuck in. */
const LOOK_EVERY_MS = 5000;
/** How long a form stays open, unfinished, before the Architect offers help. */
export const STUCK_AFTER_MS = 60_000;
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
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  // One read on every page. The widget used to fetch every agent, the approval
  // queue and the reader's failed runs to count them (#2248); the server asks
  // each through the scope its own page uses, and says 0 or null where the
  // reader may not look.
  const { data } = useQuery({
    queryKey: qk.runs.assistantSignals(orgId),
    queryFn: () => apiClient.get<SignalsRead>("/assistant/signals"),
    enabled: orgId !== "",
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
    pendingApprovals: data?.pending_approvals ?? 0,
    noAgents: data !== undefined && !data.has_agents,
    failedRunId: data?.failed_run_id ?? null,
    stuckIn,
  };
}
