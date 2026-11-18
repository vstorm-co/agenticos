"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import {
  browserCredentialRequest,
  isBrowserCredentialAudienceCurrent,
  readBrowserCredentialPolicy,
  updateBrowserCredentialPolicy,
} from "@/lib/browser-credentials-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type { AgentList } from "@/types/agents";
import type { OrganizationMemberList } from "@/types/organization";
import type { SecretList } from "@/types/secrets";
import type { BrowserCredentialPolicyEdit } from "@/types/browser-credentials";

export function useBrowserCredentialAudience() {
  const actor = useAuthStore((state) => state.user?.id);
  const organization = useOrgStore((state) => state.activeOrgId);
  return { actor, organization };
}

export const browserCredentialKeys = {
  policy: (actor: string | undefined, organization: string | null, secretId: string) =>
    ["browser-credentials", actor, organization, "policy", secretId] as const,
  choices: (actor: string | undefined, organization: string | null, kind: string) =>
    ["browser-credentials", actor, organization, "choices", kind] as const,
};

export function useBrowserCredentialPolicy(secretId: string, enabled: boolean) {
  const audience = useBrowserCredentialAudience();
  const client = useQueryClient();
  const queryKey = browserCredentialKeys.policy(audience.actor, audience.organization, secretId);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => readBrowserCredentialPolicy(audience, secretId, signal),
    enabled: enabled && !!audience.actor && !!audience.organization,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  const update = useMutation({
    mutationKey: [...queryKey, "update"],
    mutationFn: (value: BrowserCredentialPolicyEdit) =>
      updateBrowserCredentialPolicy(audience, secretId, value),
    retry: false,
    gcTime: 0,
    onSuccess: (policy) => {
      if (!isBrowserCredentialAudienceCurrent(audience)) return;
      client.setQueryData(queryKey, policy);
      void client.invalidateQueries({ queryKey: qk.secrets.list() });
    },
    onError: () => {
      if (isBrowserCredentialAudienceCurrent(audience)) void client.invalidateQueries({ queryKey });
    },
  });
  // A refused fresh read cannot leave an old grant editable.
  return { ...query, data: enabled && !query.error ? query.data : undefined, update };
}

/** User-requested pagination: never silently treats the first page as the whole audience. */
type ChoiceLists = { agents: AgentList; members: OrganizationMemberList; secrets: SecretList };

export function useBrowserCredentialChoices<K extends keyof ChoiceLists>(kind: K, enabled = true) {
  const audience = useBrowserCredentialAudience();
  const query = useInfiniteQuery({
    queryKey: browserCredentialKeys.choices(audience.actor, audience.organization, kind),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      browserCredentialRequest(
        audience,
        (options) => {
          const path =
            kind === "members"
              ? `/orgs/${encodeURIComponent(audience.organization!)}/members`
              : `/${kind}`;
          return apiClient.get<ChoiceLists[K]>(path, {
            ...options,
            params: { skip: String(pageParam), limit: "100" },
          });
        },
        signal,
      ),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((count, page) => count + page.items.length, 0);
      return last.items.length > 0 && loaded < last.total ? loaded : undefined;
    },
    enabled: enabled && !!audience.actor && !!audience.organization,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  return { ...query, data: enabled && !query.error ? query.data : undefined };
}
