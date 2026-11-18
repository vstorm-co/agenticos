"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-error";
import {
  changeBrowserProcedureTeaching,
  discardBrowserProcedureTeaching,
  isBrowserProcedureTeachingAudienceCurrent,
  proposeBrowserProcedureTeaching,
  readBrowserProcedureTeaching,
  startBrowserProcedureTeaching,
  stopBrowserProcedureTeaching,
} from "@/lib/browser-procedure-teaching-api";
import {
  isBrowserProcedureTeachingId,
  browserProcedureTeachingDraftPending,
  BROWSER_PROCEDURE_TEACHING_POLL_MS,
  BROWSER_PROCEDURE_TEACHING_POLL_WINDOW_MS,
} from "@/lib/browser-procedure-teaching-review";
import { qk } from "@/lib/query-keys";
import type {
  BrowserProcedureTeaching,
  BrowserProcedureTeachingChange,
  BrowserProcedureTeachingPropose,
} from "@/types/browser-procedure-teaching";
import type { BrowserProcedureTeachingStartAttempt } from "@/lib/browser-procedure-teaching-attempts";
import { useBrowserProcedureTeachingAudience } from "./use-browser-procedure-teaching-settings";

export type BrowserProcedureTeachingCommand =
  | { action: "change"; session: BrowserProcedureTeaching; body: BrowserProcedureTeachingChange }
  | { action: "stop" | "discard"; session: BrowserProcedureTeaching }
  | {
      action: "propose";
      session: BrowserProcedureTeaching;
      revision: number;
      body: BrowserProcedureTeachingPropose;
    };
function matchingIdentity(next: BrowserProcedureTeaching, previous: BrowserProcedureTeaching) {
  return (
    next.id === previous.id &&
    next.run_id === previous.run_id &&
    next.call_id === previous.call_id &&
    next.tab_id === previous.tab_id &&
    next.agent_id === previous.agent_id &&
    next.target_skill_id === previous.target_skill_id
  );
}
export function useBrowserProcedureTeaching(id: string | null, observedRevision?: number | null) {
  const audience = useBrowserProcedureTeachingAudience();
  const client = useQueryClient();
  const key = useMemo(
    () => qk.browserProcedureTeaching.detail(audience.actor, audience.organization, id ?? ""),
    [audience.actor, audience.organization, id],
  );
  const ready =
    !!audience.actor && !!audience.organization && !!id && isBrowserProcedureTeachingId(id);
  const [pollUntil, setPollUntil] = useState(
    () => Date.now() + BROWSER_PROCEDURE_TEACHING_POLL_WINDOW_MS,
  );
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    // Local deadlines must keep expiring after the finite network polling window.
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);
  const query = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const result = await readBrowserProcedureTeaching(audience, id!, signal);
      if (result.id !== id) {
        // i18n-exempt: a fixed internal identity refusal; transport text is not displayed.
        throw new Error("Teaching response identity mismatch");
      }
      return result;
    },
    enabled: ready,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
    refetchInterval: (entry) =>
      now < pollUntil &&
      (browserProcedureTeachingDraftPending(entry.state.data) ||
        entry.state.data?.status === "recording" ||
        entry.state.data?.status === "paused" ||
        entry.state.data?.reason_code === "task_not_completed")
        ? BROWSER_PROCEDURE_TEACHING_POLL_MS
        : false,
  });
  useEffect(() => {
    if (ready && observedRevision != null && observedRevision > (query.data?.revision ?? 0))
      void client.invalidateQueries({ queryKey: key });
  }, [ready, observedRevision, query.data?.revision, client, key]);
  const command = useMutation({
    mutationKey: [...key, "command"],
    retry: false,
    gcTime: 0,
    onMutate: () => client.cancelQueries({ queryKey: key }),
    mutationFn: async (input: BrowserProcedureTeachingCommand) => {
      const current = input.session;
      const next =
        input.action === "change"
          ? await changeBrowserProcedureTeaching(audience, current.id, current.revision, input.body)
          : input.action === "propose"
            ? await proposeBrowserProcedureTeaching(
                audience,
                current.id,
                input.revision,
                input.body,
              )
            : input.action === "stop"
              ? await stopBrowserProcedureTeaching(audience, current.id)
              : await discardBrowserProcedureTeaching(audience, current.id);
      if (!matchingIdentity(next, current)) {
        // i18n-exempt: a mismatched response cannot settle a saved uncertain attempt.
        throw new Error("Teaching response identity mismatch");
      }
      return next;
    },
    onSuccess: (next) => {
      if (!isBrowserProcedureTeachingAudienceCurrent(audience)) return;
      client.setQueryData<BrowserProcedureTeaching>(key, (previous) =>
        previous && previous.revision > next.revision ? previous : next,
      );
      setPollUntil(Date.now() + BROWSER_PROCEDURE_TEACHING_POLL_WINDOW_MS);
    },
    onSettled: () => {
      if (isBrowserProcedureTeachingAudienceCurrent(audience))
        void client.invalidateQueries({
          queryKey: qk.browserProcedureTeaching.all(audience.actor, audience.organization),
        });
    },
  });
  const authorityRefused =
    command.error instanceof ApiError &&
    [401, 403, 404].includes(command.error.status) &&
    command.submittedAt >= query.dataUpdatedAt;
  const refresh = async () => {
    if (!ready) return undefined;
    setNow(Date.now());
    setPollUntil(Date.now() + BROWSER_PROCEDURE_TEACHING_POLL_WINDOW_MS);
    return query.refetch();
  };
  return {
    audience,
    ready,
    query,
    command,
    refresh,
    now,
    session: !query.error && !authorityRefused ? query.data : undefined,
    pollingEnded: now >= pollUntil,
  };
}
export function useBrowserProcedureTeachingStart() {
  const audience = useBrowserProcedureTeachingAudience();
  const client = useQueryClient();
  return useMutation({
    mutationKey: [
      ...qk.browserProcedureTeaching.all(audience.actor, audience.organization),
      "start",
    ],
    retry: false,
    gcTime: 0,
    mutationFn: async (attempt: BrowserProcedureTeachingStartAttempt) => {
      const next = await startBrowserProcedureTeaching(
        audience,
        attempt.body,
        attempt.targetSkillId,
      );
      if (
        next.id !== attempt.body.request_id ||
        next.run_id !== attempt.body.run_id ||
        next.call_id !== attempt.body.call_id ||
        next.tab_id !== attempt.body.tab_id ||
        next.target_skill_id !== attempt.targetSkillId
      ) {
        // i18n-exempt: fixed internal refusal, not a page-derived message.
        throw new Error("Teaching start response identity mismatch");
      }
      return next;
    },
    onSuccess: (next) => {
      if (!isBrowserProcedureTeachingAudienceCurrent(audience)) return;
      client.setQueryData(
        qk.browserProcedureTeaching.detail(audience.actor, audience.organization, next.id),
        next,
      );
      void client.invalidateQueries({
        queryKey: qk.browserProcedureTeaching.list(audience.actor, audience.organization),
      });
    },
    onError: () => {
      if (isBrowserProcedureTeachingAudienceCurrent(audience))
        void client.invalidateQueries({
          queryKey: qk.browserProcedureTeaching.all(audience.actor, audience.organization),
        });
    },
  });
}
