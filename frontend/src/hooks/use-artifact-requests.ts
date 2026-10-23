"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  ArtifactAccessRequested,
  ArtifactShareRequest,
  ArtifactShareRequestList,
  ArtifactVersionReview,
} from "@/types/artifact";

/** The server refused to share a page whose data its owner has not confirmed (409). */
export function isConsentRequired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === "CONSENT_REQUIRED";
}

/**
 * The requests about one page that the caller may see, pending ones first.
 *
 * `include_decided` adds the approved, declined and voided ones. Read only while
 * `enabled` - the Share dialog open, or the strip counting what waits on a decider.
 */
export function useArtifactRequests(artifactId: string, includeDecided: boolean, enabled: boolean) {
  const query = useQuery({
    queryKey: qk.artifacts.requests(artifactId, includeDecided),
    queryFn: () =>
      apiClient.get<ArtifactShareRequestList>(`/apps/${artifactId}/share-requests`, {
        params: includeDecided ? { include_decided: "true" } : undefined,
      }),
    enabled,
  });
  const items = query.data?.items ?? [];
  // Pending first, as the server sends them newest first: a stable sort keeps that order.
  const ordered = [...items].sort(
    (a, b) => Number(b.status === "pending") - Number(a.status === "pending"),
  );
  return {
    requests: ordered,
    // Of every request the caller may see: the server sends a page of them, the
    // pending ones first.
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
  };
}

/**
 * Approve or decline one request. A 409 means it was decided or voided meanwhile,
 * so the lists are read again. A refusal for want of consent is left to the caller,
 * which offers Confirm data; anything else toasts.
 */
export function useArtifactRequestActions(artifactId: string) {
  const t = useTranslations("artifacts.requests");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const settle = async () => {
    // Everything under the page: an approval changes who reads it, and with what data.
    await queryClient.invalidateQueries({ queryKey: qk.artifacts.detail(artifactId) });
    await queryClient.invalidateQueries({ queryKey: qk.sharing.detail("artifact", artifactId) });
  };
  const refused = (error: unknown) => {
    if (isConsentRequired(error)) return;
    void queryClient.invalidateQueries({ queryKey: qk.artifacts.requestsAll(artifactId) });
    toast.error(getErrorMessage(error, tErrors));
  };

  const approve = useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<ArtifactShareRequest>(
        `/apps/${artifactId}/share-requests/${requestId}/approve`,
      ),
    onSuccess: async () => {
      await settle();
      toast.success(t("approved"));
    },
    onError: refused,
  });
  const decline = useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<ArtifactShareRequest>(
        `/apps/${artifactId}/share-requests/${requestId}/decline`,
      ),
    onSuccess: async () => {
      await settle();
      toast.success(t("declined"));
    },
    onError: refused,
  });
  return { approve, decline };
}

/** Ask for access to a page the caller may not open; the note is optional. */
export function useRequestAccess(artifactId: string) {
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (note: string | null) =>
      apiClient.post<ArtifactAccessRequested>(`/apps/${artifactId}/access-requests`, {
        note,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.artifacts.detail(artifactId) }),
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
}

/**
 * What a version's page queries read that the audience's version did not.
 *
 * Never cached: the owner decides on the tables as they are now.
 */
export function useVersionReview(artifactId: string, versionId: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.artifacts.review(artifactId, versionId),
    queryFn: () =>
      apiClient.get<ArtifactVersionReview>(`/apps/${artifactId}/versions/${versionId}/review`),
    enabled,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });
}
