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

export function useCodingAccounts() {
  const tenant = useTenantId();
  const user = useAuthStore((state) => state.user?.id);
  const guard = useTenantGuard();
  const client = useQueryClient();
  const key = qk.codingAccounts.mine(`${tenant ?? ""}:${user ?? ""}`);
  const invalidate = () => {
    if (guard(tenant) && useAuthStore.getState().user?.id === user)
      void client.invalidateQueries({ queryKey: key });
  };
  const accounts = useQuery({
    queryKey: key,
    queryFn: listCodingAccounts,
    enabled: !!tenant && !!user,
  });
  const connect = useMutation({ mutationFn: connectCodingAccount, onSuccess: invalidate });
  const start = useMutation({ mutationFn: startCodingSignIn });
  const complete = useMutation({ mutationFn: completeCodingSignIn, onSuccess: invalidate });
  const disconnect = useMutation({ mutationFn: disconnectCodingAccount, onSuccess: invalidate });
  const consent = useMutation({ mutationFn: enableCodingAccount, onSuccess: invalidate });
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
