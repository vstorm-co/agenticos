"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useBrowserCredentialAudience } from "./use-browser-credentials";
import {
  browserContinuationPending,
  isBrowserContinuationSource,
} from "@/lib/browser-credential-continuation";
import {
  confirmBrowserContinuation,
  readBrowserContinuation,
  requestBrowserContinuation,
} from "@/lib/browser-credential-continuation-api";
import { isBrowserCredentialAudienceCurrent } from "@/lib/browser-credentials-api";
import {
  BROWSER_CREDENTIAL_POLL_MS,
  BROWSER_CREDENTIAL_POLL_WINDOW_MS,
} from "@/lib/browser-credential-review";
import { qk } from "@/lib/query-keys";
import { ApiError } from "@/lib/api-error";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import type {
  BrowserContinuationConfirmation,
  BrowserContinuationRequest,
  BrowserCredentialContinuation,
} from "@/types/browser-credential-continuation";

interface ReceiptCache {
  generation: number;
  refused: boolean;
  recoveryRequired: boolean;
  row: BrowserCredentialContinuation | null;
}
let observationSequence = 0;
const observation = (
  row: BrowserCredentialContinuation | null,
  refused = false,
  recoveryRequired = false,
): ReceiptCache => ({
  generation: ++observationSequence,
  refused,
  recoveryRequired,
  row,
});
// The continuation service's closed refusals are 400; authentication, hidden resources,
// canonical approval conflicts and invalid consent bodies also fail closed.
const authorityRefusal = (error: unknown) =>
  error instanceof ApiError && [400, 401, 403, 404, 409, 422].includes(error.status);

/** Every observation fences older requests, including after cache eviction and remount. */
export function useBrowserCredentialContinuation(source: BrowserCredentialPlan, enabled: boolean) {
  const audience = useBrowserCredentialAudience();
  const client = useQueryClient();
  const key = qk.browserContinuations.receipt(audience.actor, audience.organization, source);
  const [now, setNow] = useState(Date.now);
  const [pollUntil, setPollUntil] = useState(() => Date.now() + BROWSER_CREDENTIAL_POLL_WINDOW_MS);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);
  const ready =
    enabled && !!audience.actor && !!audience.organization && isBrowserContinuationSource(source);
  const fence = () => {
    const cached = client.getQueryData<ReceiptCache>(key);
    return cached?.generation ?? 0;
  };
  const refuse = (before: number, authoritative = false) => {
    if (isBrowserCredentialAudienceCurrent(audience) && (authoritative || fence() === before))
      client.setQueryData<ReceiptCache>(key, observation(null, true));
  };
  const receipt = useQuery<ReceiptCache>({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const before = fence();
      try {
        const row = await readBrowserContinuation(audience, source, signal);
        const current = client.getQueryData<ReceiptCache>(key);
        // A newer receipt or refusal remains authoritative over this older read.
        return current && current.generation !== before ? current : observation(row);
      } catch (error) {
        const current = client.getQueryData<ReceiptCache>(key);
        const authoritative = authorityRefusal(error);
        if (!authoritative && current && current.generation !== before) return current;
        if (!signal.aborted) refuse(before, authoritative);
        throw error;
      }
    },
    enabled: ready,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
    refetchInterval: (query) =>
      now < pollUntil &&
      query.state.status !== "error" &&
      !query.state.data?.refused &&
      browserContinuationPending(query.state.data?.row)
        ? BROWSER_CREDENTIAL_POLL_MS
        : false,
  });
  const beforeWrite = () => ({ fence: fence() });
  const accept = (row: BrowserCredentialContinuation, context: { fence: number } | undefined) => {
    if (isBrowserCredentialAudienceCurrent(audience) && context && fence() === context.fence) {
      client.setQueryData<ReceiptCache>(key, observation(row));
      if (row.saved_sign_in_id)
        void client.invalidateQueries({ queryKey: qk.browserSignIns.mine(row.organization_id) });
    }
  };
  const reject = (error: unknown, context: { fence: number } | undefined) => {
    if (!isBrowserCredentialAudienceCurrent(audience)) return;
    const current = client.getQueryData<ReceiptCache>(key);
    const authoritative = authorityRefusal(error);
    if (!context || !current || authoritative || current.generation === context.fence) {
      refuse(context?.fence ?? fence(), authoritative);
      return;
    }
    // Keep newer evidence, but share the need for a post-failure read with every observer.
    client.setQueryData<ReceiptCache>(key, observation(current.row, current.refused, true));
  };
  const prepare = useMutation({
    mutationKey: [...key, "prepare"],
    retry: false,
    gcTime: 0,
    mutationFn: (body: BrowserContinuationRequest) =>
      requestBrowserContinuation(audience, source, body),
    onMutate: beforeWrite,
    onSuccess: (row, _body, context) => accept(row, context),
    onError: (error, _body, context) => reject(error, context),
  });
  const confirm = useMutation({
    mutationKey: [...key, "confirm"],
    retry: false,
    gcTime: 0,
    mutationFn: ({
      row,
      body,
    }: {
      row: BrowserCredentialContinuation;
      body: BrowserContinuationConfirmation;
    }) => confirmBrowserContinuation(audience, source, row, body),
    onMutate: beforeWrite,
    onSuccess: (row, _body, context) => accept(row, context),
    onError: (error, _body, context) => reject(error, context),
  });
  const refresh = async () => {
    if (!ready) return;
    const current = Date.now();
    setNow(current);
    setPollUntil(current + BROWSER_CREDENTIAL_POLL_WINDOW_MS);
    await receipt.refetch();
  };
  const unavailable = !ready || receipt.isError || receipt.data?.refused === true;
  return {
    audience,
    ready,
    receipt,
    prepare,
    confirm,
    refresh,
    now,
    row: unavailable ? undefined : receipt.data?.row,
    unavailable,
    needsRecovery: receipt.data?.recoveryRequired === true,
    pollingEnded: now >= pollUntil,
    current:
      ready &&
      receipt.isFetchedAfterMount &&
      !receipt.isFetching &&
      !unavailable &&
      !receipt.data?.recoveryRequired &&
      now < pollUntil,
  };
}

export type BrowserContinuationControl = ReturnType<typeof useBrowserCredentialContinuation>;
