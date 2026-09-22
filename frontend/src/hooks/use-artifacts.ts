"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  ArtifactDetail,
  ArtifactList,
  ArtifactVersionList,
  ArtifactView,
} from "@/types/artifact";

/** Which slice of the artifacts the caller may open to ask for. */
export interface ArtifactQuery {
  /** Matched against the title and the name, by the database. */
  search?: string;
  skip?: number;
  limit?: number;
}

/**
 * The artifacts the caller may open, most recently published first.
 *
 * Searching and paging happen on the server, so `total` is the count before
 * paging. There is no create here: an artifact is written by an agent's run,
 * and a person changes one by asking the agent again.
 */
export function useArtifacts({ search = "", skip = 0, limit = PAGE_SIZE }: ArtifactQuery = {}) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.artifacts.list({ search, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
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
 * One artifact, its kept versions, and what a member with `edit` may do to it.
 *
 * A 404 is the answer for a missing artifact, one in another organization and
 * one whose access was revoked alike, so `error` is what the page reads to
 * say "not available" rather than guessing which of the three it was.
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
    enablePublicLink,
    disablePublicLink,
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
