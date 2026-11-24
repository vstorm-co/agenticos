"use client";

import { useEffect, useRef, useState } from "react";
import { Network, Plus } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { Button, ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { useAuthStore, useOrgStore } from "@/stores";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { getNetworkEnrollment } from "@/lib/network-connections-api";
import { Perm } from "@/types/permissions";
import type { NetworkConnection, NetworkEnrollment } from "@/types/network-connections";
import { usePermissions } from "@/hooks/use-permissions";
import {
  isCurrentNetworkConnectionScope,
  useNetworkConnectionState,
  useNetworkConnections,
} from "@/hooks/use-network-connections";
import type { NetworkConnectionScopeKey } from "@/hooks/use-network-connections";
import { NetworkConnectionCard } from "./network-connection-card";
import { NetworkConnectionCreateDialog } from "./network-connection-create-dialog";
import { NetworkConnectionEnrollmentDialog } from "./network-connection-enrollment-dialog";

interface EnrollmentSession {
  connection: NetworkConnection;
  scope: NetworkConnectionScopeKey;
  enrollment: NetworkEnrollment;
  invalidated: boolean;
}

interface BusyRequest {
  key: string;
  generation: number;
}

const CONNECTION_PAGE_SIZE = 50;

function hasLiveEnrollment(enrollment: NetworkEnrollment): boolean {
  if (!enrollment.attempt_id || !enrollment.expires_at) return false;
  const deadline = Date.parse(enrollment.expires_at);
  return Number.isFinite(deadline) && deadline > Date.now();
}

export function NetworkConnections() {
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const scopeKey = JSON.stringify([userId ?? null, orgId ?? null]);
  return <NetworkConnectionsForScope key={scopeKey} />;
}

function NetworkConnectionsForScope() {
  const t = useTranslations("networkConnections");
  const tErrors = useTranslations("errors");
  const permissions = usePermissions();
  const [skip, setSkip] = useState(0);
  const [busyRequests, setBusyRequests] = useState<Record<string, number>>({});
  const api = useNetworkConnections({
    enabled: permissions.isLoaded && permissions.can(Perm.networksView),
    skip,
    limit: CONNECTION_PAGE_SIZE,
  });
  const [createOpen, setCreateOpen] = useState(false);
  const [enrollment, setEnrollment] = useState<EnrollmentSession | null>(null);
  const [createdConnectionId, setCreatedConnectionId] = useState<string | null>(null);
  const enrollmentRequest = useRef<AbortController | null>(null);
  const busyGeneration = useRef(0);
  const manageScope = permissions.scopeOf(Perm.networksManage);
  const createScopes = {
    user: manageScope !== "none",
    org: manageScope === "shared" || manageScope === "team" || manageScope === "all",
  };
  const canCreate = createScopes.user || createScopes.org;
  const sessionIsCurrent = Boolean(
    enrollment &&
    api.scope &&
    enrollment.scope.userId === api.scope.userId &&
    enrollment.scope.orgId === api.scope.orgId,
  );
  const candidateSession = sessionIsCurrent ? enrollment : null;
  const enrollmentState = useNetworkConnectionState(
    candidateSession?.connection.id ?? null,
    Boolean(candidateSession),
    candidateSession?.scope ?? null,
  );
  const enrollmentInactive = Boolean(
    candidateSession &&
    (enrollmentState.data?.desired_state === "paused" ||
      enrollmentState.data?.desired_state === "revoked"),
  );
  const terminalAuthState =
    enrollmentState.data?.auth_state === "authenticated" ||
    enrollmentState.data?.auth_state === "expired" ||
    enrollmentState.data?.auth_state === "error";
  const enrollmentHasExpired = Boolean(
    candidateSession && !hasLiveEnrollment(candidateSession.enrollment),
  );
  const shouldClearEnrollment = Boolean(
    candidateSession &&
    ((enrollmentInactive && !candidateSession.invalidated) ||
      ((terminalAuthState || enrollmentHasExpired) &&
        (candidateSession.enrollment.login_url !== null ||
          candidateSession.enrollment.expires_at !== null))),
  );
  if (candidateSession && shouldClearEnrollment) {
    setEnrollment((current) => {
      if (
        !current ||
        current.connection.id !== candidateSession.connection.id ||
        current.scope.userId !== candidateSession.scope.userId ||
        current.scope.orgId !== candidateSession.scope.orgId ||
        current.enrollment.attempt_id !== candidateSession.enrollment.attempt_id
      ) {
        return current;
      }
      return {
        ...current,
        invalidated: current.invalidated || enrollmentInactive,
        enrollment: { ...current.enrollment, expires_at: null, login_url: null },
      };
    });
  }
  const activeSession =
    candidateSession && !enrollmentInactive && !candidateSession.invalidated
      ? candidateSession
      : null;
  const enrollmentConnectionId = activeSession?.connection.id ?? null;
  const enrollmentAttemptId = activeSession?.enrollment.attempt_id ?? null;
  const enrollmentExpiresAt = activeSession?.enrollment.expires_at ?? null;
  const enrollmentUserId = activeSession?.scope.userId ?? null;
  const enrollmentOrgId = activeSession?.scope.orgId ?? null;
  const dialogEnrollment = activeSession
    ? hasLiveEnrollment(activeSession.enrollment)
      ? activeSession.enrollment
      : { ...activeSession.enrollment, expires_at: null, login_url: null }
    : null;

  function busyKey(id: string): string | null {
    return api.scope ? `${api.scope.userId}:${api.scope.orgId}:${id}` : null;
  }

  function beginBusy(id: string): BusyRequest | null {
    const key = busyKey(id);
    if (!key) return null;
    const request = { key, generation: ++busyGeneration.current };
    setBusyRequests((current) => ({ ...current, [key]: request.generation }));
    return request;
  }

  function finishBusy(request: BusyRequest | null) {
    if (!request) return;
    setBusyRequests((current) => {
      if (current[request.key] !== request.generation) return current;
      const next = { ...current };
      delete next[request.key];
      return next;
    });
  }

  function isBusy(id: string): boolean {
    const key = busyKey(id);
    return key !== null && busyRequests[key] !== undefined;
  }

  useEffect(
    () => () => {
      enrollmentRequest.current?.abort();
    },
    [],
  );
  const updateCachedConnection = api.updateCachedConnection;
  useEffect(() => {
    if (enrollmentState.data && activeSession) updateCachedConnection(enrollmentState.data);
  }, [activeSession, enrollmentState.data, updateCachedConnection]);

  useEffect(() => {
    if (!candidateSession || !enrollmentInactive) return;
    enrollmentRequest.current?.abort();
    enrollmentRequest.current = null;
  }, [candidateSession, enrollmentInactive]);

  useEffect(() => {
    if (!enrollmentConnectionId || !enrollmentUserId || !enrollmentOrgId) return;
    const terminal =
      enrollmentState.data?.auth_state === "authenticated" ||
      enrollmentState.data?.auth_state === "expired" ||
      enrollmentState.data?.auth_state === "error";
    const inactive =
      enrollmentState.data?.desired_state === "paused" ||
      enrollmentState.data?.desired_state === "revoked";
    if (inactive) {
      enrollmentRequest.current?.abort();
      enrollmentRequest.current = null;
      return;
    }
    if (terminal) return;
    if (!enrollmentAttemptId || !enrollmentExpiresAt) return;

    const initialDeadline = Date.parse(enrollmentExpiresAt);
    if (!Number.isFinite(initialDeadline) || initialDeadline <= Date.now()) {
      return;
    }

    const controller = new AbortController();
    enrollmentRequest.current?.abort();
    enrollmentRequest.current = controller;
    let timer: number | undefined;
    let stopped = false;
    const clearPrivateUrl = (next?: NetworkEnrollment) => {
      setEnrollment((current) => {
        if (
          !current ||
          current.connection.id !== enrollmentConnectionId ||
          current.scope.userId !== enrollmentUserId ||
          current.scope.orgId !== enrollmentOrgId ||
          current.enrollment.attempt_id !== enrollmentAttemptId
        ) {
          return current;
        }
        return {
          ...current,
          enrollment: next
            ? { ...next, login_url: null }
            : { ...current.enrollment, expires_at: null, login_url: null },
        };
      });
    };
    const expireEnrollment = () => {
      stopped = true;
      clearPrivateUrl();
      controller.abort();
      if (enrollmentRequest.current === controller) enrollmentRequest.current = null;
    };
    const deadlineTimer = window.setTimeout(
      expireEnrollment,
      Math.max(0, initialDeadline - Date.now()),
    );
    const pollEnrollment = async () => {
      if (stopped || controller.signal.aborted) return;
      if (
        !isCurrentNetworkConnectionScope({
          userId: enrollmentUserId,
          orgId: enrollmentOrgId,
        })
      ) {
        controller.abort();
        return;
      }
      if (Date.now() >= initialDeadline) {
        expireEnrollment();
        return;
      }
      try {
        const latest = await getNetworkEnrollment(enrollmentConnectionId, controller.signal);
        if (
          stopped ||
          controller.signal.aborted ||
          !isCurrentNetworkConnectionScope({
            userId: enrollmentUserId,
            orgId: enrollmentOrgId,
          })
        ) {
          return;
        }
        const latestDeadline = latest.expires_at ? Date.parse(latest.expires_at) : NaN;
        if (!latest.attempt_id || !latest.expires_at) {
          stopped = true;
          clearPrivateUrl({ ...latest, expires_at: null, login_url: null });
          return;
        }
        if (latest.attempt_id !== enrollmentAttemptId) {
          stopped = true;
          clearPrivateUrl();
          return;
        }
        if (!Number.isFinite(latestDeadline)) {
          stopped = true;
          clearPrivateUrl();
          return;
        }
        if (latestDeadline <= Date.now()) {
          stopped = true;
          clearPrivateUrl();
          return;
        }
        setEnrollment((current) => {
          if (
            !current ||
            current.connection.id !== enrollmentConnectionId ||
            current.scope.userId !== enrollmentUserId ||
            current.scope.orgId !== enrollmentOrgId ||
            current.enrollment.attempt_id !== enrollmentAttemptId
          ) {
            return current;
          }
          return { ...current, enrollment: { ...latest, login_url: null } };
        });
      } catch (caught) {
        if (controller.signal.aborted || stopped) return;
        if (caught instanceof ApiError && caught.status === 404) {
          stopped = true;
          clearPrivateUrl();
          return;
        }
      }
      if (!stopped && !controller.signal.aborted) {
        timer = window.setTimeout(() => void pollEnrollment(), 2_000);
      }
    };

    timer = window.setTimeout(() => void pollEnrollment(), 2_000);
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
      window.clearTimeout(deadlineTimer);
      controller.abort();
      if (enrollmentRequest.current === controller) enrollmentRequest.current = null;
    };
  }, [
    enrollmentAttemptId,
    enrollmentConnectionId,
    enrollmentExpiresAt,
    enrollmentOrgId,
    enrollmentState.data?.auth_state,
    enrollmentState.data?.desired_state,
    enrollmentUserId,
  ]);

  async function startEnrollment(connection: NetworkConnection) {
    const scope = api.scope;
    if (
      !scope ||
      !connection.can_manage ||
      !api.available ||
      !isCurrentNetworkConnectionScope(scope)
    )
      return;
    const busyRequest = beginBusy(connection.id);
    enrollmentRequest.current?.abort();
    enrollmentRequest.current = null;
    setEnrollment(null);
    try {
      const updated = await api.connect(connection.id);
      if (!isCurrentNetworkConnectionScope(scope)) return;
      api.updateCachedConnection(updated);
      const controller = new AbortController();
      enrollmentRequest.current = controller;
      const privateEnrollment = await getNetworkEnrollment(connection.id, controller.signal);
      if (controller.signal.aborted || !isCurrentNetworkConnectionScope(scope)) return;
      const liveEnrollment = hasLiveEnrollment(privateEnrollment);
      setEnrollment({
        connection: updated,
        scope,
        invalidated: false,
        enrollment: {
          ...(liveEnrollment
            ? privateEnrollment
            : { ...privateEnrollment, expires_at: null, login_url: null }),
        },
      });
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      if (isCurrentNetworkConnectionScope(scope)) toast.error(getErrorMessage(caught, tErrors));
    } finally {
      finishBusy(busyRequest);
    }
  }

  async function createConnection(input: { name: string; scope: "user" | "org" }) {
    const scope = api.scope;
    if (!scope || !isCurrentNetworkConnectionScope(scope)) return;
    const created = await api.create(input);
    if (!isCurrentNetworkConnectionScope(scope)) return;
    setSkip(0);
    api.updateCachedConnection(created);
    setCreatedConnectionId(created.id);
    toast.success(t("success.created"));
  }

  async function pauseConnection(connection: NetworkConnection) {
    await perform(connection, () => api.pause(connection.id), t("success.paused"));
  }

  async function refreshConnection(connection: NetworkConnection) {
    await perform(connection, () => api.refreshStatus(connection.id), t("success.refreshQueued"));
  }

  async function revokeConnection(connection: NetworkConnection): Promise<boolean> {
    return perform(connection, () => api.revoke(connection.id), t("success.revoked"));
  }

  async function perform(
    connection: NetworkConnection,
    operation: () => Promise<NetworkConnection>,
    successMessage: string,
  ): Promise<boolean> {
    if (!api.scope || !connection.can_manage || !isCurrentNetworkConnectionScope(api.scope))
      return false;
    const scope = api.scope;
    const busyRequest = beginBusy(connection.id);
    try {
      const updated = await operation();
      if (!isCurrentNetworkConnectionScope(scope)) return false;
      api.updateCachedConnection(updated);
      toast.success(successMessage);
      return true;
    } catch (caught) {
      if (isCurrentNetworkConnectionScope(scope)) toast.error(getErrorMessage(caught, tErrors));
      return false;
    } finally {
      finishBusy(busyRequest);
    }
  }

  if (!permissions.isLoaded) return <Skeleton className="h-64 rounded-xl" />;
  if (!permissions.can(Perm.networksView)) {
    return <ErrorState description={t("accessDenied")} />;
  }
  if (!api.scope) return <Skeleton className="h-64 rounded-xl" />;
  if (api.isLoading) return <Skeleton className="h-64 rounded-xl" />;
  if (api.error) {
    return (
      <div className="space-y-3">
        <ErrorState description={getErrorMessage(api.error, tErrors)} />
        <Button variant="outline" onClick={() => void api.refresh()}>
          {t("retry")}
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {api.available === false && (
        <p role="status" className="bg-muted text-muted-foreground rounded-lg p-4 text-sm">
          {t("deploymentUnavailable")}
        </p>
      )}
      <p role="note" className="bg-muted text-muted-foreground rounded-lg p-4 text-sm">
        {t("serviceAdaptersUnavailable")}
      </p>
      <ListCard
        fill
        namedByPage
        title={t("list.title")}
        counted={t("list.count", { count: api.total })}
        contentClassName="space-y-3 p-4"
        data-tour="network-connections"
        controls={
          canCreate && api.available !== false ? (
            <Button data-tour="tailscale-add" onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden />
              {t("addTailscale")}
            </Button>
          ) : undefined
        }
      >
        {api.connections.length === 0 ? (
          skip > 0 && api.total > 0 ? (
            <p role="status" className="text-muted-foreground rounded-lg p-4 text-sm">
              {t("list.pageChanged")}
            </p>
          ) : (
            <ListCardEmpty
              icon={Network}
              title={t("list.emptyTitle")}
              description={t("list.emptyDescription")}
            />
          )
        ) : (
          <ul className="space-y-3">
            {api.connections.map((connection) => (
              <li key={connection.id}>
                <NetworkConnectionCard
                  connection={connection}
                  scope={api.scope}
                  available={api.available}
                  busy={isBusy(connection.id)}
                  connectTour={
                    connection.id === createdConnectionId ? "tailscale-connect" : undefined
                  }
                  onConnect={(item) => void startEnrollment(item)}
                  onPause={(item) => void pauseConnection(item)}
                  onRefreshStatus={(item) => void refreshConnection(item)}
                  onRevoke={(item) => revokeConnection(item)}
                />
              </li>
            ))}
          </ul>
        )}
        {(api.total > CONNECTION_PAGE_SIZE || skip > 0) && (
          <nav
            className="border-border flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3"
            aria-label={t("list.paginationLabel")}
          >
            {api.connections.length > 0 && (
              <p className="text-muted-foreground text-sm">
                {t("list.paginationRange", {
                  start: skip + 1,
                  end: Math.min(skip + api.connections.length, api.total),
                  total: api.total,
                })}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={skip === 0}
                onClick={() =>
                  setSkip((current) =>
                    current >= api.total && api.total > 0
                      ? Math.floor((api.total - 1) / CONNECTION_PAGE_SIZE) * CONNECTION_PAGE_SIZE
                      : Math.max(0, current - CONNECTION_PAGE_SIZE),
                  )
                }
              >
                {t("list.previous")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={
                  api.connections.length === 0 || skip + api.connections.length >= api.total
                }
                onClick={() => setSkip((current) => current + CONNECTION_PAGE_SIZE)}
              >
                {t("list.next")}
              </Button>
            </div>
          </nav>
        )}
      </ListCard>
      <NetworkConnectionCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        available={api.available}
        scopes={createScopes}
        saving={api.isCreating}
        onCreate={createConnection}
      />
      {activeSession && dialogEnrollment && (
        <NetworkConnectionEnrollmentDialog
          open
          onOpenChange={(open) => {
            if (open) return;
            enrollmentRequest.current?.abort();
            setEnrollment(null);
          }}
          connection={enrollmentState.data ?? activeSession.connection}
          enrollment={dialogEnrollment}
          currentState={enrollmentState.data}
          stateLoading={enrollmentState.isLoading || enrollmentState.isFetching}
          stateError={Boolean(enrollmentState.error)}
          canManage={(enrollmentState.data ?? activeSession.connection).can_manage}
          available={api.available}
          refreshing={api.isRefreshing}
          onRefreshStatus={() => void refreshConnection(activeSession.connection)}
          onRestart={() => void startEnrollment(activeSession.connection)}
        />
      )}
    </div>
  );
}
