"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import { qk } from "@/lib/query-keys";
import {
  listCodingAccounts,
  connectCodingAccount,
  disconnectCodingAccount,
  enableCodingAccount,
  completeCodingSignIn,
  startCodingSignIn,
} from "@/lib/coding-accounts-api";

interface CodingScope {
  tenant: string | null;
  user: string | undefined;
}

export function useCodingAccounts() {
  const tenant = useTenantId();
  const user = useAuthStore((state) => state.user?.id);
  const guard = useTenantGuard();
  const client = useQueryClient();
  const key = qk.codingAccounts.mine(`${tenant ?? ""}:${user ?? ""}`);
  // Mutation observers receive updated callbacks after a render. Capture the
  // initiating audience in mutation context, rather than the latest closure.
  const lifecycle = {
    onMutate: (): CodingScope => ({ tenant, user }),
    onSuccess: (_data: unknown, _variables: unknown, started: CodingScope | undefined) => {
      if (started && guard(started.tenant) && useAuthStore.getState().user?.id === started.user)
        void client.invalidateQueries({
          queryKey: qk.codingAccounts.mine(`${started.tenant ?? ""}:${started.user ?? ""}`),
        });
    },
  };
  const accounts = useQuery({
    queryKey: key,
    queryFn: listCodingAccounts,
    enabled: !!tenant && !!user,
  });
  const connect = useMutation({ mutationFn: connectCodingAccount, ...lifecycle });
  const start = useMutation({ mutationFn: startCodingSignIn });
  const complete = useMutation({ mutationFn: completeCodingSignIn, ...lifecycle });
  const disconnect = useMutation({ mutationFn: disconnectCodingAccount, ...lifecycle });
  const consent = useMutation({ mutationFn: enableCodingAccount, ...lifecycle });
  return {
    accounts,
    connect,
    complete,
    disconnect,
    consent,
    start,
    scope: `${tenant ?? ""}:${user ?? ""}`,
    ready: !!tenant && !!user,
  };
}
