"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { exceptOpenPage, qk } from "@/lib/query-keys";
import { isConsentRequired } from "@/hooks/use-artifact-requests";
import type { SharingDeferred } from "@/types/artifact";
import type {
  GrantSubject,
  ResourceGrant,
  ResourceSharing,
  ShareInput,
  SharingResourceType,
  Visibility,
} from "@/types/sharing";

/**
 * Where each resource type's sharing endpoints are mounted.
 *
 * The backend generates the same four routes per type, so the prefix is the
 * only thing that differs between sharing an agent and sharing a collection.
 */
const SHARING_ROOT = {
  agent: "/agents",
  skill: "/skills",
  // `/kb`, which is where the template mounts knowledge bases and therefore
  // where the generated sharing routes land. This read `/knowledge-bases` - a
  // path the app has never served - and went unnoticed because the panel is
  // only mounted on agents so far.
  collection: "/kb",
  secret: "/secrets",
  table: "/tables",
  artifact: "/artifacts",
} as const satisfies Record<SharingResourceType, string>;

/**
 * The resource's own queries, which carry its visibility too.
 *
 * A list row and a detail page both read `visibility` from the resource, not
 * from the sharing endpoint, so a change made in the panel left them showing
 * the old reach until they happened to refetch - an artifact's page kept saying
 * "only people with access" over a page the whole organization could open.
 */
const RESOURCE_KEYS = {
  agent: qk.agents.all,
  skill: qk.skills.all,
  collection: qk.kb.all,
  secret: qk.secrets.all,
  table: qk.tables.all,
  artifact: qk.artifacts.all,
} as const satisfies Record<SharingResourceType, () => readonly string[]>;

/**
 * A resource type's guard may turn a widening into a request for its owner to decide
 * (202), which applies nothing: the body says so where a grant or the sharing never would.
 */
function isDeferred(result: unknown): result is SharingDeferred {
  return typeof result === "object" && result !== null && "request_id" in result;
}

interface SharingOptions {
  /** A page's data has no consent that would let it be shared: the caller offers Confirm data. */
  onConsentRequired?: () => void;
}

/**
 * Who reaches one resource: its owner, its visibility, and its explicit grants.
 *
 * Mutations invalidate rather than patch. Changing a visibility can change the
 * grant list the server reports back, and a level change is an upsert whose
 * result the client cannot derive - guessing is how a panel starts showing a
 * share that was never written.
 */
export function useSharing(
  resourceType: SharingResourceType,
  resourceId: string | null,
  { onConsentRequired }: SharingOptions = {},
) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("sharing");
  const queryClient = useQueryClient();
  const base = `${SHARING_ROOT[resourceType]}/${resourceId}/sharing`;

  const { data, isLoading } = useQuery({
    queryKey: qk.sharing.detail(resourceType, resourceId ?? ""),
    queryFn: () => apiClient.get<ResourceSharing>(base),
    enabled: !!resourceId,
  });

  const invalidate = useCallback(async () => {
    const queryKey = qk.sharing.detail(resourceType, resourceId ?? "");
    // Cancel an in-flight read before invalidating: invalidateQueries dedupes
    // its refetch onto a fetch already running, so a read that began before this
    // mutation committed resolves with the pre-write body, marks the query
    // fresh, and the panel keeps the old value until a reload (#154). Cancelling
    // first makes the invalidation dispatch a genuinely new, post-commit fetch.
    await queryClient.cancelQueries({ queryKey });
    await queryClient.invalidateQueries({ queryKey });
  }, [queryClient, resourceType, resourceId]);

  // A refusal for want of consent is the dialog's to offer a way out of; the rest toast.
  const refused = (error: unknown) => {
    if (onConsentRequired !== undefined && isConsentRequired(error)) onConsentRequired();
    else toast.error(getErrorMessage(error, tErrors));
  };
  // Nothing was applied: the request is what changed, and the Requests section lists it.
  const requested = async (deferred: SharingDeferred) => {
    await queryClient.invalidateQueries({ queryKey: qk.artifacts.requestsAll(resourceId ?? "") });
    toast.success(
      deferred.waiting_for === null
        ? t("requestSentNobody")
        : t("requestSent", { name: deferred.waiting_for }),
    );
  };

  const share = useMutation({
    mutationFn: (input: ShareInput) =>
      apiClient.put<ResourceGrant | SharingDeferred>(`${base}/grants`, input),
    onSuccess: async (result) => {
      if (isDeferred(result)) return requested(result);
      await invalidate();
      toast.success(t("sharingUpdated"));
    },
    onError: refused,
  });

  // Two endpoints rather than one keyed on a kind, because a user id and a group
  // id are both bare UUIDs: one path taking either could not tell which it was
  // handed.
  const revoke = useMutation({
    mutationFn: (subject: GrantSubject) =>
      subject.kind === "group"
        ? apiClient.delete<void>(`${base}/group-grants/${subject.id}`)
        : apiClient.delete<void>(`${base}/grants/${subject.id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("accessRemoved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const setVisibility = useMutation({
    mutationFn: (visibility: Visibility) =>
      apiClient.patch<ResourceSharing | SharingDeferred>(`${base}/visibility`, { visibility }),
    onSuccess: async (result) => {
      if (isDeferred(result)) return requested(result);
      await invalidate();
      // An artifact open beside the panel keeps its page: who else may open it
      // changes nothing the viewer is reading.
      await queryClient.invalidateQueries({
        queryKey: RESOURCE_KEYS[resourceType](),
        predicate: resourceType === "artifact" ? exceptOpenPage(resourceId) : undefined,
      });
      toast.success(t("visibilityUpdated"));
    },
    onError: refused,
  });

  return { sharing: data, isLoading, share, revoke, setVisibility };
}
