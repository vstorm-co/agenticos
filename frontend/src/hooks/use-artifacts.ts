"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { unlockPublicArtifact } from "@/lib/public-artifact-api";
import { qk } from "@/lib/query-keys";
import type {
  ArtifactAgent,
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
  skip = 0,
  limit = PAGE_SIZE,
}: ArtifactQuery = {}) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.artifacts.list({ search, agentId, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      if (agentId) params.set("agent_id", agentId);
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
 * A 404 is the answer for a missing artifact, one in another organization and
 * one whose access was revoked alike, so a 404 in `error` is what the page reads
 * to say "not available" rather than guessing which of the three it was. Any
 * other failure is the request's, not the artifact's, and `refetch` is how the
 * page offers to try again.
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
    enabled: detail.data !== undefined,
  });

  const settle = (artifact: ArtifactDetail) => {
    queryClient.setQueryData(qk.artifacts.detail(artifactId), artifact);
    void queryClient.invalidateQueries({ queryKey: qk.artifacts.all(), exact: false });
  };
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const enablePublicLink = useMutation({
    mutationFn: () => apiClient.put<ArtifactDetail>(`/artifacts/${artifactId}/public-link`),
    onSuccess: (artifact) => {
      settle(artifact);
      toast.success(t("publicLinkReady"));
    },
    onError: fail,
  });
  const disablePublicLink = useMutation({
    mutationFn: () => apiClient.delete<ArtifactDetail>(`/artifacts/${artifactId}/public-link`),
    onSuccess: (artifact) => {
      settle(artifact);
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
      settle(artifact);
      toast.success(t("publicLinkSaved"));
    },
  });
  const restoreVersion = useMutation({
    mutationFn: (versionId: string) =>
      apiClient.post<ArtifactDetail>(`/artifacts/${artifactId}/versions/${versionId}/restore`),
    onSuccess: (artifact) => {
      settle(artifact);
      toast.success(t("versionRestored", { version: artifact.current_version?.number ?? 0 }));
    },
    onError: fail,
  });
  const follow = useMutation({
    mutationFn: (on: boolean) =>
      on
        ? apiClient.put<ArtifactDetail>(`/artifacts/${artifactId}/follow`)
        : apiClient.delete<ArtifactDetail>(`/artifacts/${artifactId}/follow`),
    onSuccess: (artifact) => {
      queryClient.setQueryData(qk.artifacts.detail(artifactId), artifact);
      toast.success(t(artifact.following ? "followed" : "unfollowed"));
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
    follow,
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

/** Opening a public link that asks for a password, from the stranger's browser. */
export function usePublicArtifactUnlock(publicKey: string) {
  const { apiUrl } = usePublicConfig();
  return useMutation({
    mutationFn: (password: string) => unlockPublicArtifact(apiUrl, publicKey, password),
  });
}
