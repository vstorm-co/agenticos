"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useBrowserCredentialAudience } from "./use-browser-credentials";
import {
  confirmBrowserCredentialPlan,
  isBrowserCredentialAudienceCurrent,
  readBrowserCredentialEligibility,
  readBrowserCredentialPlan,
  readBrowserCredentialSubmission,
  submitBrowserCredentialPlan,
  type BrowserSubmissionAttempt,
} from "@/lib/browser-credentials-api";
import {
  BROWSER_CREDENTIAL_POLL_MS,
  BROWSER_CREDENTIAL_POLL_WINDOW_MS,
  browserCredentialDeadlineLive,
  browserCredentialPending,
  browserCredentialPlanMatches,
  browserCredentialSubmissionMatches,
  isBrowserCredentialId,
} from "@/lib/browser-credential-review";
import { isBrowserContinuationSource } from "@/lib/browser-credential-continuation";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";

export function useBrowserCredentialPlan(
  runId: string,
  planId: string,
  callId?: string,
  tabId?: string,
) {
  const audience = useBrowserCredentialAudience();
  const client = useQueryClient();
  const [pollUntil, setPollUntil] = useState(() => Date.now() + BROWSER_CREDENTIAL_POLL_WINDOW_MS);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => {
      const current = Date.now();
      setNow(current);
      if (current >= pollUntil) clearInterval(timer);
    }, 1_000);
    return () => clearInterval(timer);
  }, [pollUntil]);
  const prefix = ["browser-credentials", audience.actor, audience.organization] as const;
  const key = [...prefix, "plan", runId, planId] as const;
  const ready =
    !!audience.actor &&
    !!audience.organization &&
    isBrowserCredentialId(runId) &&
    isBrowserCredentialId(planId);
  const receipt = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => readBrowserCredentialPlan(audience, runId, planId, signal),
    enabled: ready,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
    refetchInterval: (query) =>
      now < pollUntil && browserCredentialPending(query.state.data)
        ? BROWSER_CREDENTIAL_POLL_MS
        : false,
  });
  const plan = browserCredentialPlanMatches(receipt.data, runId, planId, callId, tabId)
    ? receipt.data
    : undefined;
  // A protected continuation's review names the credential its submit used, so
  // an acknowledged continuation source reads eligibility as a pending fill does.
  const needsEligibility =
    !!plan &&
    ((plan.operation === "fill" &&
      (plan.state === "awaiting_confirmation" || plan.state === "filled")) ||
      isBrowserContinuationSource(plan));
  const eligibility = useQuery({
    queryKey: [
      ...prefix,
      "eligibility",
      runId,
      plan?.call_id,
      plan?.tab_id,
      plan?.authorization_generation,
    ],
    queryFn: ({ signal }) =>
      readBrowserCredentialEligibility(audience, runId, plan!.call_id, plan!.tab_id, signal),
    enabled: ready && needsEligibility,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
    refetchInterval: () =>
      now < pollUntil &&
      !!plan &&
      browserCredentialDeadlineLive(
        plan.state === "filled" ? plan.submission_expires_at : plan.expires_at,
        now,
      )
        ? BROWSER_CREDENTIAL_POLL_MS
        : false,
  });
  const submissionKey = (parent: BrowserCredentialPlan) =>
    [
      ...prefix,
      "submission",
      parent.run_id,
      parent.id,
      parent.authorization_generation,
      parent.document_id,
    ] as const;
  const needsSubmission = !!plan && plan.operation === "fill" && plan.state === "filled";
  const submission = useQuery({
    queryKey: plan ? submissionKey(plan) : [...prefix, "submission", runId, planId],
    queryFn: ({ signal }) => readBrowserCredentialSubmission(audience, runId, planId, signal),
    enabled: ready && needsSubmission,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
    refetchInterval: (query) => {
      if (now >= pollUntil || !plan) return false;
      return browserCredentialPending(query.state.data) ||
        (query.state.data == null && browserCredentialDeadlineLive(plan.submission_expires_at, now))
        ? BROWSER_CREDENTIAL_POLL_MS
        : false;
    },
  });
  const confirm = useMutation({
    mutationKey: [...key, "confirm"],
    retry: false,
    gcTime: 0,
    mutationFn: async ({
      receipt: frozen,
      approve,
    }: {
      receipt: BrowserCredentialPlan;
      approve: boolean;
    }) => {
      const next = await confirmBrowserCredentialPlan(audience, frozen, approve);
      if (
        !browserCredentialPlanMatches(
          next,
          frozen.run_id,
          frozen.id,
          frozen.call_id,
          frozen.tab_id,
        ) ||
        next.document_id !== frozen.document_id ||
        next.authorization_generation !== frozen.authorization_generation
      ) {
        // i18n-exempt: fixed internal refusal; page/transport errors are not displayed.
        throw new Error("Browser credential response identity mismatch");
      }
      return next;
    },
    onSuccess: (next) => {
      if (isBrowserCredentialAudienceCurrent(audience)) client.setQueryData(key, next);
    },
    onSettled: () => {
      if (isBrowserCredentialAudienceCurrent(audience))
        void client.invalidateQueries({ queryKey: key });
    },
  });
  const submit = useMutation({
    mutationKey: [...key, "submit"],
    retry: false,
    gcTime: 0,
    mutationFn: async ({
      parent,
      attempt,
    }: {
      parent: BrowserCredentialPlan;
      attempt: BrowserSubmissionAttempt;
    }) => {
      const child = await submitBrowserCredentialPlan(audience, parent.run_id, parent.id, attempt);
      if (!browserCredentialSubmissionMatches(parent, child)) {
        // i18n-exempt: a mismatched response cannot settle an uncertain submission.
        throw new Error("Browser submission response identity mismatch");
      }
      return child;
    },
    onSuccess: (child, { parent }) => {
      if (isBrowserCredentialAudienceCurrent(audience)) {
        client.setQueryData(submissionKey(parent), child);
      }
    },
  });
  const refresh = async () => {
    if (!ready) return undefined;
    const current = Date.now();
    setNow(current);
    setPollUntil(current + BROWSER_CREDENTIAL_POLL_WINDOW_MS);
    const [, , child] = await Promise.all([
      receipt.refetch(),
      needsEligibility ? eligibility.refetch() : Promise.resolve(undefined),
      needsSubmission ? submission.refetch() : Promise.resolve(undefined),
    ]);
    return child;
  };
  return {
    audience,
    ready,
    receipt,
    plan,
    eligibility,
    submission,
    confirm,
    submit,
    refresh,
    now,
    pollingEnded: now >= pollUntil,
  };
}
