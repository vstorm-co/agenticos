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
  ArtifactList,
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
}: ArtifactQuery = {}) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.artifacts.list({ search, agentId, includeArchived, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      if (agentId) params.set("agent_id", agentId);
      if (includeArchived) params.set("include_archived", "true");
      params.set("skip", String(skip));
      params.set("limit", String(limit));
      return apiClient.get<ArtifactList>(`/artifacts?${params}`);
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
    mutationFn: (id: string) => apiClient.post<ArtifactDetail>(`/artifacts/${id}/archive`),
    onSuccess: (artifact) => {
      settle(artifact);
      toast.success(t("archived"));
    },
    onError: fail,
  });
  const unarchive = useMutation({
    mutationFn: (id: string) => apiClient.post<ArtifactDetail>(`/artifacts/${id}/unarchive`),
    onSuccess: (artifact) => {
      settle(artifact);
      toast.success(t("unarchived"));
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/artifacts/${id}`),
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
    queryFn: () => apiClient.get<{ items: ArtifactAgent[] }>("/artifacts/agents"),
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
    queryFn: () => apiClient.get<ArtifactDetail>(`/artifacts/${artifactId}`),
    retry: false,
  });
  const versions = useQuery({
    queryKey: qk.artifacts.versions(artifactId),
    queryFn: () => apiClient.get<ArtifactVersionList>(`/artifacts/${artifactId}/versions`),
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
    mutationFn: () => apiClient.put<ArtifactDetail>(`/artifacts/${artifactId}/public-link`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: false });
      toast.success(t("publicLinkReady"));
    },
    onError: fail,
  });
  const disablePublicLink = useMutation({
    mutationFn: () => apiClient.delete<ArtifactDetail>(`/artifacts/${artifactId}/public-link`),
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
      apiClient.patch<ArtifactDetail>(`/artifacts/${artifactId}/public-link`, changes),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: false });
      toast.success(t("publicLinkSaved"));
    },
  });
  const restoreVersion = useMutation({
    mutationFn: (versionId: string) =>
      apiClient.post<ArtifactDetail>(`/artifacts/${artifactId}/versions/${versionId}/restore`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("versionRestored", { version: artifact.current_version?.number ?? 0 }));
    },
    onError: fail,
  });
  // Both reload the page: an archived one serves nothing, and a restored one is
  // drawn again from a fresh address.
  const archive = useMutation({
    mutationFn: () => apiClient.post<ArtifactDetail>(`/artifacts/${artifactId}/archive`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("archived"));
    },
    onError: fail,
  });
  const unarchive = useMutation({
    mutationFn: () => apiClient.post<ArtifactDetail>(`/artifacts/${artifactId}/unarchive`),
    onSuccess: (artifact) => {
      settle(artifact, { reloadPage: true });
      toast.success(t("unarchived"));
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => apiClient.delete<void>(`/artifacts/${artifactId}`),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: qk.artifacts.detail(artifactId) });
      await queryClient.invalidateQueries({ queryKey: qk.artifacts.all() });
      toast.success(t("deleted"));
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
    remove,
  };
}

/**
 * A signed address for the frame, minted fresh for each version shown.
 *
 * Never cached past its own expiry: the address is valid for minutes, so a
 * frame redrawn from a stale one would load nothing. `staleTime: 0` and no
 * retry, because a refusal here is the page being gone rather than a blip.
 */
export function useArtifactView(artifactId: string, versionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: qk.artifacts.view(artifactId, versionId),
    queryFn: () => {
      const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
      return apiClient.get<ArtifactView>(`/artifacts/${artifactId}/view${query}`);
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
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: qk.artifacts.data(artifactId, versionId ?? ""),
    queryFn: async () => {
      const data = await apiClient.get<ArtifactData>(
        `/artifacts/${artifactId}/versions/${versionId}/data`,
      );
      if (!data.current) {
        for (const queryKey of [
          qk.artifacts.detail(artifactId),
          qk.artifacts.versions(artifactId),
          qk.artifacts.view(artifactId, null),
        ]) {
          void queryClient.invalidateQueries({ queryKey, exact: true });
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
