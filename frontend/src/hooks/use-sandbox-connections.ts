"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { qk } from "@/lib/query-keys";
import {
  createSandboxConnection,
  deleteSandboxConnection,
  listSandboxConnections,
  listSandboxRuntimes,
  listSandboxSessions,
  probeSandboxService,
  readLocalSandboxService,
  readSandboxEvents,
  readSandboxOperations,
  type SandboxOperationList,
  type SandboxOperationQuery,
  readSandboxPolicy,
  storeLocalSandboxCredential,
  updateSandboxConnection,
  type SandboxConnectionInput,
  type SandboxConnectionPatch,
  type SandboxConnectionRecord,
  type SandboxEventList,
  type SandboxLocalService,
  type SandboxPolicy,
  type SandboxRuntimeOption,
  type SandboxSessionList,
} from "@/lib/sandbox-connections-api";

interface UseSandboxConnectionsResult {
  connections: SandboxConnectionRecord[];
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (input: SandboxConnectionInput) => Promise<SandboxConnectionRecord>;
  update: (id: string, patch: SandboxConnectionPatch) => Promise<SandboxConnectionRecord>;
  remove: (id: string) => Promise<void>;
}

/**
 * The places this organization's sandboxes run.
 *
 * Every mutation invalidates the whole list rather than patching one row,
 * because promoting a connection to default demotes another one server-side.
 * Patching the edited row would leave two rows claiming to be the default until
 * something else refetched, and "which host does an agent with no connection
 * get" is precisely the question that view answers.
 */
export function useSandboxConnections(): UseSandboxConnectionsResult {
  const t = useTranslations("sandboxes");
  const queryClient = useQueryClient();

  const {
    data: connections = [],
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: qk.sandboxConnections.list(),
    queryFn: listSandboxConnections,
  });

  const invalidate = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.sandboxConnections.all() });
  }, [queryClient]);

  const create = useCallback(
    async (input: SandboxConnectionInput) => {
      const created = await createSandboxConnection(input);
      await invalidate();
      return created;
    },
    [invalidate],
  );

  const update = useCallback(
    async (id: string, patch: SandboxConnectionPatch) => {
      const updated = await updateSandboxConnection(id, patch);
      await invalidate();
      return updated;
    },
    [invalidate],
  );

  const remove = useCallback(
    async (id: string) => {
      await deleteSandboxConnection(id);
      await invalidate();
    },
    [invalidate],
  );

  return {
    connections,
    isLoading,
    error:
      queryError instanceof Error
        ? queryError.message
        : queryError
          ? t("failedLoadConnections")
          : null,
    refresh: invalidate,
    create,
    update,
    remove,
  };
}

interface UseSandboxPolicyResult {
  policy: SandboxPolicy | null;
  isLoading: boolean;
  /** Why the service could not be asked. A string, because it is shown as one. */
  error: string | null;
  /** Ask again. Nothing here polls, so a failure stays until somebody retries. */
  refetch: () => void;
}

/**
 * What one connection's service allows, read from the service.
 *
 * Not cached beyond the session and not retried: the answer is a live fact about
 * a host, and a stale runtime list is worse than none - it offers an alias the
 * service will refuse. `enabled` is what keeps the Builder from calling this
 * before an author has chosen a connection at all.
 */
export function useSandboxPolicy(connectionId: string | null): UseSandboxPolicyResult {
  const t = useTranslations("sandboxes");
  const {
    data: policy = null,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: qk.sandboxConnections.policy(connectionId ?? "none"),
    queryFn: () => readSandboxPolicy(connectionId as string),
    enabled: connectionId !== null,
    retry: false,
    staleTime: 30_000,
  });

  return {
    policy,
    isLoading: connectionId !== null && isLoading,
    error: error instanceof Error ? error.message : error ? t("serviceSilent") : null,
    refetch: () => void refetch(),
  };
}

interface UseLocalSandboxServiceResult {
  local: SandboxLocalService | null;
  /** What this deployment ships, offered before anything has been probed. */
  runtimes: SandboxRuntimeOption[];
  isLoading: boolean;
  /** Store this deployment's own token in the vault, and answer with its id. */
  storeCredential: () => Promise<string>;
  /** Ask an unsaved address what it allows. Throws with what went wrong. */
  probe: (baseUrl: string, secretId: string | null) => Promise<SandboxPolicy>;
}

/**
 * What this deployment can already see, for the form that would otherwise ask.
 *
 * No error field, deliberately. "Nothing answered" is the normal case for a
 * deployment that runs no sandbox service, and it arrives as `url: null` rather
 * than as a failure - a dialog that showed a red line every time somebody opened
 * it on a stack without one would be reporting a problem nobody has.
 */
export function useLocalSandboxService(enabled: boolean): UseLocalSandboxServiceResult {
  const queryClient = useQueryClient();
  const { data: local = null, isLoading } = useQuery({
    queryKey: qk.sandboxConnections.local(),
    queryFn: readLocalSandboxService,
    enabled,
    retry: false,
    staleTime: 30_000,
  });

  // The catalog, not an allowlist, and static for the life of the deployment - so
  // it is fetched whenever the form is open rather than only for a new connection,
  // and never refetched. It is what makes the runtime field a populated select
  // instead of a text box waiting for somebody to press a test button.
  const { data: runtimes = [] } = useQuery({
    queryKey: qk.sandboxConnections.runtimes(),
    queryFn: listSandboxRuntimes,
    staleTime: Infinity,
    retry: false,
  });

  const storeCredential = useCallback(async () => {
    const created = await storeLocalSandboxCredential();
    // The vault list is what the credential picker reads, and the entry has to be
    // in it before the id this returns can be selected.
    await queryClient.invalidateQueries({ queryKey: qk.secrets.all() });
    return created.secret_id;
  }, [queryClient]);

  return {
    local,
    runtimes,
    isLoading: enabled && isLoading,
    storeCredential,
    probe: probeSandboxService,
  };
}

interface UseSandboxSessionsResult {
  listing: SandboxSessionList | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * What is running on one host, right now.
 *
 * Refetched on an interval rather than cached, because every field it shows -
 * idle seconds, memory, whether a sandbox is still alive - is only true at the
 * moment it was read. `usage` is opt-in: the service samples each sandbox
 * individually for it, so a page that shows twenty must ask before paying that.
 */
export function useSandboxSessions(
  connectionId: string | null,
  usage = false,
): UseSandboxSessionsResult {
  const t = useTranslations("sandboxes");
  const {
    data: listing = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxConnections.sessions(connectionId ?? "none", usage),
    queryFn: () => listSandboxSessions(connectionId as string, usage),
    enabled: connectionId !== null,
    retry: false,
    refetchInterval: 10_000,
  });

  return {
    listing,
    isLoading: connectionId !== null && isLoading,
    error: error instanceof Error ? error.message : error ? t("serviceSilent") : null,
  };
}

interface UseSandboxEventsResult {
  log: SandboxEventList | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * The durable record of what agents did in this organization's sandboxes.
 *
 * Replaces the service's own log in the product: that one is a 200-entry ring
 * buffer in the service's memory, so it could not answer a week later or after a
 * restart (#1061). These rows can, and the filters narrow the request rather than
 * an array the client already holds - which is what makes a pager mean something.
 *
 * `placeholderData` keeps the previous page on screen while the next one loads, so
 * paging does not blink through an empty table.
 *
 * Re-read on an interval while mounted: rows land when a run's transaction
 * commits, so a dialog opened over a working sandbox would otherwise sit on the
 * page as it stood at open - empty or stale - until something else happened to
 * refetch it. Ten seconds, because the rows arrive per turn, not per keystroke.
 */
export function useSandboxOperations(query: SandboxOperationQuery): {
  log: SandboxOperationList | null;
  isLoading: boolean;
  error: string | null;
} {
  const t = useTranslations("sandboxes");
  const {
    data = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxConnections.operations({ ...query }),
    queryFn: () => readSandboxOperations(query),
    placeholderData: (previous) => previous,
    refetchInterval: 10_000,
    retry: false,
  });

  return {
    log: data,
    isLoading,
    error: error instanceof Error ? error.message : error ? t("activityLogUnreadable") : null,
  };
}

/**
 * The service's own live log for one sandbox, as it is happening.
 *
 * Kept beside `useSandboxOperations` rather than replaced by it, and the
 * difference is timing: our rows are written into the run's transaction, so a
 * turn's operations arrive together when the turn commits. The service answers
 * mid-turn. So this is what a dashboard row watching a working sandbox reads, and
 * the durable record is what an audit reads.
 *
 * The whole buffer every time rather than incrementally. `after` exists for a
 * watcher that keeps state, and a widget that mounts with a row is not one.
 */
export function useSandboxEvents(
  connectionId: string | null,
  sessionId: string | null,
): UseSandboxEventsResult {
  const t = useTranslations("sandboxes");
  const {
    data: log = null,
    isLoading,
    error,
  } = useQuery({
    queryKey: qk.sandboxConnections.events(connectionId ?? "none", sessionId ?? "none"),
    queryFn: () => readSandboxEvents(connectionId as string, sessionId as string),
    enabled: connectionId !== null && sessionId !== null,
    retry: false,
  });

  return {
    log,
    isLoading: connectionId !== null && sessionId !== null && isLoading,
    error: error instanceof Error ? error.message : error ? t("activityLogUnreadable") : null,
  };
}
