"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import { qk } from "@/lib/query-keys";
import { ApiError } from "@/lib/api-error";
import {
  readCodingAccountUsage,
  refreshCodingAccountUsage,
  type CodingAccount,
  type CodingAccountUsage,
} from "@/lib/coding-accounts-api";

const POLL_INTERVAL_MS = 3_000;
const POLL_WINDOW_MS = 3 * 60_000;

class UsageIdentityChanged extends Error {}

function accessRefused(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404);
}

const REDACTED_EVIDENCE: Pick<CodingAccount, "usage" | "model_catalog"> = {
  usage: {
    status: "unknown",
    source: "unavailable",
    observed_at: null,
    observation_age_seconds: null,
    valid_until: null,
    windows: [],
    reason_code: null,
  },
  model_catalog: {
    status: "unknown",
    source: "unavailable",
    observed_at: null,
    valid_until: null,
    model_ids: [],
    reason_code: null,
  },
};

interface RefreshScope {
  tenant: string | null;
  user: string | undefined;
  scope: string;
  accountId: string;
  generation: string;
  key: ReturnType<typeof qk.codingAccounts.usage>;
}

/** Explicit probes write; every automatic refresh here only reads cached metadata. */
export function useCodingAccountUsage(account: CodingAccount) {
  const tenant = useTenantId();
  const user = useAuthStore((state) => state.user?.id);
  const guard = useTenantGuard();
  const client = useQueryClient();
  const scope = `${tenant ?? ""}:${user ?? ""}`;
  const key = qk.codingAccounts.usage(scope, account.id, account.generation);
  const identity = JSON.stringify(key);
  const ready = !!tenant && !!user;
  const supported = account.harness === "codex" && account.secret_kind === "openai_codex";
  const [clock, setClock] = useState(() => Date.now());
  const [polling, setPolling] = useState<{
    identity: string;
    pending: boolean;
    until: number | null;
  }>({ identity: "", pending: false, until: null });
  const pollUntil = polling.identity === identity ? polling.until : null;

  const currentAudience = (started: RefreshScope | undefined): started is RefreshScope =>
    started !== undefined &&
    guard(started.tenant) &&
    useAuthStore.getState().user?.id === started.user &&
    account.id === started.accountId &&
    account.generation === started.generation;

  const redact = (started: RefreshScope) => {
    if (!currentAudience(started)) return;
    // Null persists the refusal across remounts and Check again's pending GET.
    // Stale list props must not reseed private evidence or authorize a refresh.
    client.setQueryData<CodingAccountUsage | null>(started.key, null);
    client.setQueryData<{ items: CodingAccount[] }>(
      qk.codingAccounts.mine(started.scope),
      (cached) =>
        cached && {
          ...cached,
          items: cached.items.map((row) =>
            row.id === started.accountId && row.generation === started.generation
              ? { ...row, ...REDACTED_EVIDENCE, usage_refresh_pending: false }
              : row,
          ),
        },
    );
  };

  const usage = useQuery<CodingAccountUsage | null>({
    queryKey: key,
    queryFn: async () => {
      if (!ready || !guard(tenant) || useAuthStore.getState().user?.id !== user)
        throw new UsageIdentityChanged();
      let report: CodingAccountUsage;
      try {
        report = await readCodingAccountUsage(account.id);
      } catch (error) {
        if (accessRefused(error))
          redact({
            tenant,
            user,
            scope,
            accountId: account.id,
            generation: account.generation,
            key,
          });
        throw error;
      }
      if (!guard(tenant) || useAuthStore.getState().user?.id !== user)
        throw new UsageIdentityChanged();
      if (report.account_id !== account.id || report.generation !== account.generation) {
        void client.invalidateQueries({ queryKey: qk.codingAccounts.mine(scope), exact: true });
        throw new UsageIdentityChanged();
      }
      return report;
    },
    initialData: (): CodingAccountUsage | undefined =>
      ready
        ? {
            account_id: account.id,
            generation: account.generation,
            usage: account.usage,
            model_catalog: account.model_catalog,
            refresh_pending: account.usage_refresh_pending,
          }
        : undefined,
    enabled: ready && supported && account.enabled,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchIntervalInBackground: false,
    refetchInterval: (query) =>
      query.state.data?.refresh_pending &&
      pollUntil !== null &&
      Math.max(clock, query.state.dataUpdatedAt) < pollUntil
        ? POLL_INTERVAL_MS
        : false,
  });

  const refresh = useMutation({
    mutationKey: [...key, "refresh"],
    mutationFn: async (started: RefreshScope) => {
      if (
        !ready ||
        !supported ||
        !account.enabled ||
        !currentAudience(started) ||
        client.getQueryData(started.key) === null
      )
        throw new UsageIdentityChanged();
      const report = await refreshCodingAccountUsage({
        id: started.accountId,
        generation: started.generation,
      });
      if (report.account_id !== started.accountId || report.generation !== started.generation)
        throw new UsageIdentityChanged();
      return report;
    },
    onMutate: async (started: RefreshScope): Promise<RefreshScope> => {
      if (
        !ready ||
        !supported ||
        !account.enabled ||
        !currentAudience(started) ||
        client.getQueryData(started.key) === null
      )
        throw new UsageIdentityChanged();
      // A slower cached read must not overwrite the newly accepted pending probe.
      await client.cancelQueries({ queryKey: started.key, exact: true });
      if (!currentAudience(started)) throw new UsageIdentityChanged();
      return started;
    },
    onSuccess: (report, _variables, started) => {
      if (!currentAudience(started)) return;
      // A later refusal outranks an earlier refresh. Only a fresh authorized GET
      // can restore access; mutationFn already checked the report's identity.
      if (client.getQueryData(started.key) === null) return;
      client.setQueryData(started.key, report);
    },
    onError: async (error, _variables, started) => {
      if (accessRefused(error) && currentAudience(started)) {
        await client.cancelQueries({ queryKey: started.key, exact: true }, { revert: false });
        redact(started);
      }
    },
    onSettled: (_report, _error, _variables, started) => {
      if (currentAudience(started))
        void client.invalidateQueries({
          queryKey: qk.codingAccounts.mine(started.scope),
          exact: true,
        });
    },
  });

  const changed =
    usage.data === null ||
    usage.error instanceof UsageIdentityChanged ||
    refresh.error instanceof UsageIdentityChanged;
  const report = ready && !changed ? usage.data : undefined;
  const pending = Boolean(report?.refresh_pending && supported && account.enabled);
  const now = Math.max(clock, usage.dataUpdatedAt);
  // A new pending operation gets one window; each poll keeps that original deadline.
  if (polling.identity !== identity || polling.pending !== pending)
    setPolling({ identity, pending, until: pending ? now + POLL_WINDOW_MS : null });

  // Expiry changes the rendered evidence even when polling has stopped or no task ran.
  const deadlines = [report?.usage.valid_until, report?.model_catalog?.valid_until]
    .map((value) => (value ? Date.parse(value) : Number.NaN))
    .concat(pollUntil ?? Number.NaN)
    .filter((value) => Number.isFinite(value) && value > now);
  const nextDeadline = Math.min(...deadlines);
  useEffect(() => {
    if (!Number.isFinite(nextDeadline)) return;
    const timer = setTimeout(
      () => setClock(Date.now()),
      Math.min(2_147_483_647, Math.max(1, nextDeadline - Date.now() + 1)),
    );
    return () => clearTimeout(timer);
  }, [nextDeadline]);

  const check = () => {
    refresh.reset();
    const checkedAt = Date.now();
    setClock(checkedAt);
    if (pending) setPolling({ identity, pending: true, until: checkedAt + POLL_WINDOW_MS });
    return usage.refetch();
  };
  return {
    report,
    now,
    supported,
    ready,
    changed,
    pending,
    pollExpired: pending && pollUntil !== null && now >= pollUntil,
    checking: usage.isFetching,
    error: usage.error ?? refresh.error,
    refreshing: refresh.isPending,
    requestRefresh: () => {
      setClock(Date.now());
      refresh.mutate({
        tenant,
        user,
        scope,
        accountId: account.id,
        generation: account.generation,
        key,
      });
    },
    check,
  };
}
