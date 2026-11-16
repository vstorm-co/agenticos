"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api-error";
import {
  changeBrowserTeaching,
  discardBrowserTeaching,
  isTeachingAudienceCurrent,
  proposeBrowserTeaching,
  readBrowserTeaching,
  startBrowserTeaching,
  stopBrowserTeaching,
} from "@/lib/browser-teaching-api";
import {
  isTeachingId,
  teachingDraftPending,
  TEACHING_POLL_MS,
  TEACHING_POLL_WINDOW_MS,
} from "@/lib/browser-teaching-review";
import { qk } from "@/lib/query-keys";
import type { BrowserTeaching, TeachingChange, TeachingPropose } from "@/types/browser-teaching";
import type { TeachingStartAttempt } from "@/lib/browser-teaching-attempts";
import { useTeachingAudience } from "./use-browser-teaching-settings";

export type TeachingCommand =
  | { action: "change"; session: BrowserTeaching; body: TeachingChange }
  | { action: "stop" | "discard"; session: BrowserTeaching }
  | { action: "propose"; session: BrowserTeaching; revision: number; body: TeachingPropose };
function matchingIdentity(next: BrowserTeaching, previous: BrowserTeaching) {
  return (
    next.id === previous.id &&
    next.run_id === previous.run_id &&
    next.call_id === previous.call_id &&
    next.tab_id === previous.tab_id &&
    next.agent_id === previous.agent_id &&
    next.target_skill_id === previous.target_skill_id
  );
}
export function useBrowserTeaching(id: string | null, observedRevision?: number | null) {
  const audience = useTeachingAudience();
  const client = useQueryClient();
  const key = useMemo(
    () => qk.browserTeaching.detail(audience.actor, audience.organization, id ?? ""),
    [audience.actor, audience.organization, id],
  );
  const ready = !!audience.actor && !!audience.organization && !!id && isTeachingId(id);
  const [pollUntil, setPollUntil] = useState(() => Date.now() + TEACHING_POLL_WINDOW_MS);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    // Local deadlines must keep expiring after the finite network polling window.
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);
  const query = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const result = await readBrowserTeaching(audience, id!, signal);
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
      (teachingDraftPending(entry.state.data) ||
        entry.state.data?.status === "recording" ||
        entry.state.data?.status === "paused" ||
        entry.state.data?.reason_code === "task_not_completed")
        ? TEACHING_POLL_MS
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
    mutationFn: async (input: TeachingCommand) => {
      const current = input.session;
      const next =
        input.action === "change"
          ? await changeBrowserTeaching(audience, current.id, current.revision, input.body)
          : input.action === "propose"
            ? await proposeBrowserTeaching(audience, current.id, input.revision, input.body)
            : input.action === "stop"
              ? await stopBrowserTeaching(audience, current.id)
              : await discardBrowserTeaching(audience, current.id);
      if (!matchingIdentity(next, current)) {
        // i18n-exempt: a mismatched response cannot settle a saved uncertain attempt.
        throw new Error("Teaching response identity mismatch");
      }
      return next;
    },
    onSuccess: (next) => {
      if (!isTeachingAudienceCurrent(audience)) return;
      client.setQueryData<BrowserTeaching>(key, (previous) =>
        previous && previous.revision > next.revision ? previous : next,
      );
      setPollUntil(Date.now() + TEACHING_POLL_WINDOW_MS);
    },
    onSettled: () => {
      if (isTeachingAudienceCurrent(audience))
        void client.invalidateQueries({
          queryKey: qk.browserTeaching.all(audience.actor, audience.organization),
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
    setPollUntil(Date.now() + TEACHING_POLL_WINDOW_MS);
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
export function useTeachingStart() {
  const audience = useTeachingAudience();
  const client = useQueryClient();
  return useMutation({
    mutationKey: [...qk.browserTeaching.all(audience.actor, audience.organization), "start"],
    retry: false,
    gcTime: 0,
    mutationFn: async (attempt: TeachingStartAttempt) => {
      const next = await startBrowserTeaching(audience, attempt.body, attempt.targetSkillId);
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
      if (!isTeachingAudienceCurrent(audience)) return;
      client.setQueryData(
        qk.browserTeaching.detail(audience.actor, audience.organization, next.id),
        next,
      );
      void client.invalidateQueries({
        queryKey: qk.browserTeaching.list(audience.actor, audience.organization),
      });
    },
    onError: () => {
      if (isTeachingAudienceCurrent(audience))
        void client.invalidateQueries({
          queryKey: qk.browserTeaching.all(audience.actor, audience.organization),
        });
    },
  });
}
