"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import {
  getBrowserTeaching,
  proposeBrowserTeaching,
  reviewBrowserTeaching,
  type BrowserTeaching,
  type ReviewedStep,
} from "@/lib/browser-teaching-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";

/** How often a queued proposal build is checked on until it settles. */
const PROPOSING_POLL_MS = 2000;

export interface UseBrowserTeachingResult {
  teaching: BrowserTeaching | undefined;
  isLoading: boolean;
  error: unknown;
  /** Who is reading, so a view can drop its draft when the identity changes. */
  identity: string;
  saveReview: (steps: ReviewedStep[]) => Promise<BrowserTeaching | undefined>;
  /** Propose from `base`, the session a review save just returned, or the one in hand. */
  propose: (name: string, base?: BrowserTeaching) => Promise<void>;
  isSaving: boolean;
  isProposing: boolean;
}

/**
 * One Teach a task recording under review, and the two writes a reviewer makes.
 *
 * The cache key names the organization and the person, so switching either
 * reads afresh instead of showing someone else's steps. Each write sends the
 * revision it was based on; a refusal (a stale revision included) is toasted
 * and the session is read again.
 */
export function useBrowserTeaching(id: string): UseBrowserTeachingResult {
  const t = useTranslations("errors");
  const queryClient = useQueryClient();
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "current";
  const userId = useAuthStore((state) => state.user?.id) ?? "anonymous";
  const key = qk.browserTeaching.one(orgId, userId, id);
  const { data, isLoading, error } = useQuery({
    queryKey: key,
    queryFn: () => getBrowserTeaching(id),
    refetchInterval: (query) =>
      query.state.data?.status === "proposing" ? PROPOSING_POLL_MS : false,
  });

  const settle = {
    onSuccess: (next: BrowserTeaching) => queryClient.setQueryData(key, next),
    onError: async (cause: unknown) => {
      toast.error(getErrorMessage(cause, t));
      await queryClient.invalidateQueries({ queryKey: key });
    },
  };
  const reviewing = useMutation({
    mutationFn: ({ revision, steps }: { revision: number; steps: ReviewedStep[] }) =>
      reviewBrowserTeaching(id, revision, steps),
    ...settle,
  });
  const proposing = useMutation({
    mutationFn: ({ revision, name }: { revision: number; name: string }) =>
      proposeBrowserTeaching(id, revision, name),
    ...settle,
  });

  return {
    teaching: data,
    isLoading,
    error,
    identity: `${orgId}:${userId}`,
    saveReview: async (steps) =>
      data === undefined
        ? undefined
        : reviewing.mutateAsync({ revision: data.revision, steps }).catch(() => undefined),
    propose: async (name, base = data) => {
      if (base === undefined) return;
      await proposing.mutateAsync({ revision: base.revision, name }).catch(() => undefined);
    },
    isSaving: reviewing.isPending,
    isProposing: proposing.isPending,
  };
}
