"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type {
  NewSecret,
  Secret,
  SecretEdit,
  SecretKindInfo,
  SecretKindList,
  SecretList,
  SecretPurposeList,
  StorableSecretKind,
} from "@/types/secrets";

/**
 * The organization's vault: secrets a capability can be bound to, and the
 * shapes they may take.
 *
 * Write-only, like a provider key. A value goes in and what comes back is a
 * name, a kind and four characters - there is no endpoint that returns a
 * plaintext, so nothing here can display one.
 *
 * The kinds are fetched rather than listed in code. Every form on this surface
 * is generated from the JSON Schema the server publishes, which is what keeps a
 * field added to `AwsCredentialsSecret` from being a field this app never
 * offers.
 */
export function useSecrets() {
  const queryClient = useQueryClient();

  const secrets = useQuery({
    queryKey: qk.secrets.list(),
    queryFn: () => apiClient.get<SecretList>("/secrets"),
  });

  const kinds = useQuery({
    queryKey: qk.secrets.kinds(),
    queryFn: () => apiClient.get<SecretKindList>("/secrets/kinds"),
    // The set of shapes changes when the platform is redeployed, never while a
    // dialog is open. Refetching it on every focus buys nothing.
    staleTime: Infinity,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.secrets.list() }),
    [queryClient],
  );

  // Neither writing mutation toasts its failure: a name already in use is the
  // refusal people actually hit, and it belongs beside the field that holds the
  // name rather than in a toast that takes it away again. The dialogs decide,
  // through `submitFailure`.
  const create = useMutation({
    mutationFn: (data: NewSecret) => apiClient.post<Secret>("/secrets", data),
    onSuccess: async (secret) => {
      await invalidate();
      toast.success(`Stored ${secret.name} (…${secret.hint})`);
    },
  });

  const rotate = useMutation({
    mutationFn: ({ id, ...data }: SecretEdit) => apiClient.patch<Secret>(`/secrets/${id}`, data),
    onSuccess: async (secret) => {
      await invalidate();
      // Said in full because rotation is the one operation here that destroys
      // something: the id survives, so every agent bound to it keeps working,
      // and the value it used a second ago is gone.
      toast.success(`Rotated ${secret.name}. It now ends ${secret.hint}; the old value is gone.`);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/secrets/${id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success("Secret deleted. Any agent using it fails at its next run.");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return {
    secrets: secrets.data?.items ?? [],
    kinds: kinds.data?.items ?? [],
    isLoading: secrets.isLoading || kinds.isLoading,
    /**
     * Why the list is empty, when it is empty because the request failed.
     *
     * `GET /secrets` is gated on `connections:manage`, which a member editing
     * their own agent does not have - so a refusal arrives here as a 403 and an
     * empty array. Anything that says something *about the organization* on the
     * strength of an empty list ("no API key stored yet") has to look here
     * first, or it states as fact something it was never told.
     */
    listError: secrets.error,
    create,
    rotate,
    remove,
  };
}

/** The kind's published schema, or null while the catalog is still loading. */
export function kindInfo(
  kinds: readonly SecretKindInfo[],
  kind: StorableSecretKind,
): SecretKindInfo | null {
  return kinds.find((entry) => entry.kind === kind) ?? null;
}

/**
 * What a secret can be for.
 *
 * Fetched rather than listed in code: the model providers are generated from
 * the same table the runtime builds clients out of, so a copy here would drift
 * the moment one is added - and the symptom is a provider nobody can key.
 * Cached indefinitely; it changes on redeploy, not on a mutation.
 */
export function useSecretPurposes() {
  const { data, isLoading } = useQuery({
    queryKey: qk.secrets.purposes(),
    queryFn: () => apiClient.get<SecretPurposeList>("/secrets/purposes"),
    staleTime: Infinity,
  });

  return { purposes: data?.items ?? [], isLoading };
}
