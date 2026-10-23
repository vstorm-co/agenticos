"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { PAGE_SIZE } from "@/components/ui";
import { ApiError, apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { unlockPublicArtifact } from "@/lib/public-artifact-api";
import { exceptOpenPage, qk } from "@/lib/query-keys";
import type {
  ArtifactAgent,
  ArtifactData,
  ArtifactDetail,
  ArtifactDisclosure,
  ArtifactList,
  ArtifactPublicDataDisclosure,
  ArtifactPublicLinkUpdate,
  ArtifactVersionList,
  ArtifactView,
} from "@/types/artifact";

/** Which slice of the artifacts the caller may open to ask for. */
export interface ArtifactQuery {
  /** Matched against the title and the name, by the database. */
  search?: string;
  /** Only the pages this agent published; null for every agent. */
  agentId?: string | null;
  /** List archived pages too; they are left out otherwise. */
  includeArchived?: boolean;
  skip?: number;
  limit?: number;
  /** Only what is shared with this group (#2124); null for every group. */
  groupId?: string | null;
  /** Only the pages made in this project's chats; null for every project. */
  projectId?: string | null;
}

/**
 * The artifacts the caller may open, most recently published first.
 *
 * Searching, the agent filter and paging happen on the server, so `total` is the
 * count before paging. There is no create here: an artifact is written by an
 * agent's run, and a person changes one by asking the agent again.
 */
export function useArtifacts({
  search = "",
  agentId = null,
  includeArchived = false,
  skip = 0,
  limit = PAGE_SIZE,
  groupId = null,
  projectId = null,
}: ArtifactQuery = {}) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.artifacts.list({
      search,
      agentId,
      includeArchived,
      skip,
      limit,
      groupId: groupId ?? "",
      ...(projectId ? { projectId } : {}),
    }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      if (agentId) params.set("agent_id", agentId);
      if (includeArchived) params.set("include_archived", "true");
      params.set("skip", String(skip));
      params.set("limit", String(limit));
      if (groupId) params.set("group_id", groupId);
      if (projectId) params.set("project_id", projectId);
      return apiClient.get<ArtifactList>(`/apps?${params}`);
    },
    placeholderData: (previous) => previous,
  });

  return {
    artifacts: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refetch,
  };
}

/**
 * Archive, restore and delete from the list, each by the artifact's id.
 *
 * The same requests and toasts `useArtifact` sends from the viewer, for a card
 * that has no detail loaded: a change refreshes every list and the artifact's
 * own detail, and a delete drops that detail.
 */
export function useArtifactListActions() {
  const t = useTranslations("artifacts");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const settle = (artifact: ArtifactDetail) => {
    queryClient.setQueryData(qk.artifacts.detail(artifact.id), artifact);
    void queryClient.invalidateQueries({ queryKey: qk.artifacts.all() });
  };
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const archive = useMutation({
    mutationFn: (id: string) => apiClient.post<ArtifactDetail>(`/apps/${id}/archive`),
    onSuccess: (artifact) => {
      settle(artifact);
      toast.success(t("archived"));
    },
    onError: fail,
  });
  const unarchive = useMutation({
    mutationFn: (id: string) => apiClient.post<ArtifactDetail>(`/apps/${id}/unarchive`),
    onSuccess: (artifact) => {
      settle(artifact);
      toast.success(t("unarchived"));
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/apps/${id}`),
    onSuccess: async (_, id) => {
      queryClient.removeQueries({ queryKey: qk.artifacts.detail(id) });
      await queryClient.invalidateQueries({ queryKey: qk.artifacts.all() });
      toast.success(t("deleted"));
    },
    onError: fail,
  });

  return { archive, unarchive, remove };
}

/**
 * The agents behind the artifacts the caller may open, by name - the list's filter.
 *
 * Named by the server through the artifacts themselves, so a page shared with
 * somebody offers its publisher even when that agent is not theirs to open.
 */
export function useArtifactAgents(enabled: boolean): ArtifactAgent[] {
  const { data } = useQuery({
    queryKey: qk.artifacts.agents(),
    queryFn: () => apiClient.get<{ items: ArtifactAgent[] }>("/apps/agents"),
    enabled,
  });
  return data?.items ?? [];
}

/**
 * One artifact, its kept versions, and what a member with `edit` may do to it.
 *
 * A 404 is the answer for a missing artifact, one in another organization, one
 * whose access was revoked and an archived one the caller may not edit alike, so
 * a 404 in `error` is what the page reads to say "not available" rather than
 * guessing which it was. Any other failure is the request's, not the artifact's,
 * and `refetch` is how the page offers to try again. An archived page has no
 * versions to list: the server serves nothing of it until it is restored.
 */
export function useArtifact(artifactId: string) {
  const t = useTranslations("artifacts");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: qk.artifacts.detail(artifactId),
    queryFn: () => apiClient.get<ArtifactDetail>(`/apps/${artifactId}`),
    retry: false,
  });
  const versions = useQuery({
    queryKey: qk.artifacts.versions(artifactId),
    queryFn: () => apiClient.get<ArtifactVersionList>(`/apps/${artifactId}/versions`),
    enabled: detail.data !== undefined && detail.data.archived_at === null,
  });

  // A public-link change leaves the page the viewer has open as it is: reloading
  // its signed address and data would blank a page nothing changed under. A
  // restore makes a new current version, so that one reloads the page too.
  const settle = (artifact: ArtifactDetail, { reloadPage }: { reloadPage: boolean }) => {
    queryClient.setQueryData(qk.artifacts.detail(artifactId), artifact);
    void queryClient.invalidateQueries({
      queryKey: qk.artifacts.all(),
      exact: false,
      predicate: reloadPage ? undefined : exceptOpenPage(artifactId),
    });
  };
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const enablePublicLink = useMutation({
    mutationFn: () => apiClient.put<ArtifactDetail>(`/apps/${artifactId}/public-link`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: false });
      toast.success(t("publicLinkReady"));
    },
    onError: fail,
  });
  const disablePublicLink = useMutation({
    mutationFn: () => apiClient.delete<ArtifactDetail>(`/apps/${artifactId}/public-link`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: false });
      toast.success(t("publicLinkOff"));
    },
    onError: fail,
  });
  // Refusals are left to the form that sent the change, which marks the field
  // they name rather than toasting a sentence.
  const updatePublicLink = useMutation({
    mutationFn: (changes: ArtifactPublicLinkUpdate) =>
      apiClient.patch<ArtifactDetail>(`/apps/${artifactId}/public-link`, changes),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: false });
      toast.success(t("publicLinkSaved"));
    },
  });
  const restoreVersion = useMutation({
    mutationFn: (versionId: string) =>
      apiClient.post<ArtifactDetail>(`/apps/${artifactId}/versions/${versionId}/restore`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("versionRestored", { version: artifact.current_version?.number ?? 0 }));
    },
    onError: fail,
  });
  // Both reload the page: an archived one serves nothing, and a restored one is
  // drawn again from a fresh address.
  const archive = useMutation({
    mutationFn: () => apiClient.post<ArtifactDetail>(`/apps/${artifactId}/archive`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("archived"));
    },
    onError: fail,
  });
  const unarchive = useMutation({
    mutationFn: () => apiClient.post<ArtifactDetail>(`/apps/${artifactId}/unarchive`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("unarchived"));
    },
    onError: fail,
  });
  const follow = useMutation({
    mutationFn: (on: boolean) =>
      on
        ? apiClient.put<ArtifactDetail>(`/apps/${artifactId}/follow`)
        : apiClient.delete<ArtifactDetail>(`/apps/${artifactId}/follow`),
    onSuccess: (artifact) => {
      queryClient.setQueryData(qk.artifacts.detail(artifactId), artifact);
      toast.success(t(artifact.following ? "followed" : "unfollowed"));
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => apiClient.delete<void>(`/apps/${artifactId}`),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: qk.artifacts.detail(artifactId) });
      await queryClient.invalidateQueries({ queryKey: qk.artifacts.all() });
      toast.success(t("deleted"));
    },
    onError: fail,
  });
  // Both reload the page: whose data it shows is what they change. A refused
  // confirm is the dialog's to show, so it toasts nothing - except a 409: a newer
  // version landed or the queries moved, so the page is read again (the strip
  // moves to the new latest, the disclosure with it) and the dialog closes.
  const confirmData = useMutation({
    mutationFn: ({ versionId, fingerprint }: { versionId: string; fingerprint: string }) =>
      apiClient.post<ArtifactDetail>(`/apps/${artifactId}/versions/${versionId}/consent`, {
        fingerprint,
      }),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("consent.confirmed"));
    },
    onError: (error) => {
      if (!(error instanceof ApiError && error.status === 409)) return;
      void queryClient.invalidateQueries({ queryKey: qk.artifacts.detail(artifactId) });
      void queryClient.invalidateQueries({ queryKey: qk.artifacts.requestsAll(artifactId) });
      fail(error);
    },
  });
  const withdrawConsent = useMutation({
    mutationFn: () => apiClient.delete<ArtifactDetail>(`/apps/${artifactId}/consent`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("consent.withdrawn"));
    },
    onError: fail,
  });
  // The public link's data: confirming and withdrawing change what anonymous
  // visitors read, not the page the viewer has open, so neither reloads it. A 409
  // means the queries or the audience moved since the dialog read them: the page
  // is read again and the dialog closes.
  const confirmPublicData = useMutation({
    mutationFn: (body: { fingerprint: string; audience_digest: string }) =>
      apiClient.post<ArtifactDetail>(`/apps/${artifactId}/public-data`, {
        ...body,
        confirmed: true,
      }),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: false });
      toast.success(t("publicData.confirmed"));
    },
    onError: (error) => {
      if (!(error instanceof ApiError && error.status === 409)) return;
      void queryClient.invalidateQueries({ queryKey: qk.artifacts.detail(artifactId) });
      fail(error);
    },
  });
  const withdrawPublicData = useMutation({
    mutationFn: () => apiClient.delete<ArtifactDetail>(`/apps/${artifactId}/public-data`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: false });
      toast.success(t("publicData.withdrawn"));
    },
    onError: fail,
  });
  const setAutoConsent = useMutation({
    mutationFn: (changes: { enabled: boolean; confirmed?: string }) =>
      apiClient.patch<ArtifactDetail>(`/apps/${artifactId}/auto-consent`, changes),
    onSuccess: (artifact) => settle(artifact, { reloadPage: false }),
    onError: fail,
  });

  // Reloads the page: whose data it shows is what a new owner changes.
  const changeOwner = useMutation({
    mutationFn: (userId: string) =>
      apiClient.put<ArtifactDetail>(`/apps/${artifactId}/owner`, { user_id: userId }),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("changeOwner.changed"));
    },
    onError: fail,
  });

  return {
    artifact: detail.data ?? null,
    versions: versions.data?.items ?? [],
    isLoading: detail.isLoading,
    error: detail.error,
    refetch: detail.refetch,
    enablePublicLink,
    disablePublicLink,
    updatePublicLink,
    restoreVersion,
    archive,
    unarchive,
    follow,
    remove,
    confirmData,
    withdrawConsent,
    confirmPublicData,
    withdrawPublicData,
    setAutoConsent,
    changeOwner,
  };
}

/**
 * What confirming a version's data would share, and with whom, read when the
 * dialog opens. Never cached: it is what the person agrees to, so it is read as
 * the tables are now.
 */
export function useArtifactDisclosure(artifactId: string, versionId: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.artifacts.disclosure(artifactId, versionId),
    queryFn: () =>
      apiClient.get<ArtifactDisclosure>(`/apps/${artifactId}/versions/${versionId}/disclosure`),
    enabled,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}

/**
 * What confirming the page's data for its public link would share, and with whom,
 * read when the dialog opens. Never cached, for the reason `useArtifactDisclosure` is not.
 */
export function usePublicDataDisclosure(artifactId: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.artifacts.publicDataDisclosure(artifactId),
    queryFn: () => apiClient.get<ArtifactPublicDataDisclosure>(`/apps/${artifactId}/public-data`),
    enabled,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}

/**
 * A signed address for the frame, minted fresh for each version shown.
 *
 * Never cached past its own expiry: the address is valid for minutes, so a
 * frame redrawn from a stale one would load nothing. `staleTime: 0` and no
 * retry, because a refusal here is the page being gone rather than a blip.
 *
 * `withData` asks for the page served with its bindings' data written in - only
 * the page viewer does. Thumbnails, cards and previews leave it off, and their
 * pages get none.
 */
export function useArtifactView(
  artifactId: string,
  versionId: string | null,
  enabled: boolean,
  withData = false,
) {
  return useQuery({
    queryKey: qk.artifacts.view(artifactId, versionId, withData),
    queryFn: () => {
      const params: string[] = [];
      if (versionId) params.push(`version_id=${encodeURIComponent(versionId)}`);
      if (withData) params.push("data=true");
      const query = params.length > 0 ? `?${params.join("&")}` : "";
      return apiClient.get<ArtifactView>(`/apps/${artifactId}/view${query}`);
    },
    enabled,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}

/** How many times a busy answer is tried again, and how long to wait between. */
const BUSY_RETRIES = 2;
const BUSY_RETRY_DELAY_MS = 1000;

/**
 * The live records a page version is bound to, read as the viewer.
 *
 * Never cached: every open reads the tables as they are now. Only a 429 - the
 * server's in-flight or rate gate - is tried again, twice, a second apart; any
 * other failure is the answer.
 *
 * An answer saying the version is no longer current - an agent published a
 * newer one while the page was open - marks the artifact's detail, its versions
 * and its current-version address stale, once per such answer. A frame showing
 * the current version is minted again onto the newer one, whose data is read
 * under its own key; a frame showing a picked version keeps it, since its
 * address is under that version's key.
 */
export function useArtifactData(
  artifactId: string,
  versionId: string | undefined,
  enabled: boolean,
) {
  return useDataRead(
    qk.artifacts.data(artifactId, versionId ?? ""),
    artifactId,
    versionId,
    enabled,
    true,
  );
}

/**
 * Whether each source of a page served with its data could be read, and for an
 * editor why not - without reading its records, which the page's own load did.
 *
 * Keyed by the nonce of the load it describes, so a page minted again is asked
 * again, and a read that settled before it is never taken for its own.
 */
export function useArtifactReasons(
  artifactId: string,
  versionId: string | undefined,
  nonce: string,
  enabled: boolean,
) {
  return useDataRead(
    qk.artifacts.reasons(artifactId, versionId ?? "", nonce),
    artifactId,
    versionId,
    enabled,
    false,
  );
}

function useDataRead(
  queryKey: readonly unknown[],
  artifactId: string,
  versionId: string | undefined,
  enabled: boolean,
  rows: boolean,
) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey,
    queryFn: async () => {
      const path = `/apps/${artifactId}/versions/${versionId}/data`;
      const data = rows
        ? await apiClient.get<ArtifactData>(path)
        : await apiClient.get<ArtifactData>(path, { params: { rows: "false" } });
      if (!data.current) {
        for (const key of [
          qk.artifacts.detail(artifactId),
          qk.artifacts.versions(artifactId),
          qk.artifacts.view(artifactId, null, true),
        ]) {
          void queryClient.invalidateQueries({ queryKey: key, exact: true });
        }
      }
      return data;
    },
    enabled: enabled && versionId !== undefined,
    staleTime: 0,
    gcTime: 0,
    retry: (failures, error) =>
      error instanceof ApiError && error.status === 429 && failures < BUSY_RETRIES,
    retryDelay: BUSY_RETRY_DELAY_MS,
  });
}

/** Opening a public link that asks for a password, from the stranger's browser. */
export function usePublicArtifactUnlock(publicKey: string) {
  const { apiUrl } = usePublicConfig();
  return useMutation({
    mutationFn: (password: string) => unlockPublicArtifact(apiUrl, publicKey, password),
  });
}
