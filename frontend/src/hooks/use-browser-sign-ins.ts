"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import {
  forgetSignIn,
  getMySignIns,
  getSignInBrowser,
  startSignIn,
  type BrowserSignIn,
  type SignInSession,
} from "@/lib/browser-sign-ins-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

/**
 * The sites the caller kept a sign-in to in the active organization, and forgetting one.
 *
 * Keyed on the organization, because sign-ins are kept per tenant - the same
 * person's browses in Acme and Globex start from different ones. A forget that
 * fails says so: somebody who believes a session is gone when it is not is the
 * worst outcome this screen can produce.
 */
export function useBrowserSignIns(): {
  signIns: BrowserSignIn[];
  isLoading: boolean;
  error: unknown;
  forget: (id: string) => Promise<void>;
} {
  const queryClient = useQueryClient();
  const t = useTranslations("errors");
  const activeOrgId = useOrgStore((state) => state.activeOrgId) ?? "current";
  const { data, isLoading, error } = useQuery({
    queryKey: qk.browserSignIns.mine(activeOrgId),
    queryFn: getMySignIns,
  });
  const forgetting = useMutation({
    mutationFn: forgetSignIn,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: qk.browserSignIns.mine(activeOrgId) }),
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });
  return {
    signIns: data?.items ?? [],
    isLoading,
    error,
    forget: async (id) => {
      await forgetting.mutateAsync(id).catch(() => undefined);
    },
  };
}

/**
 * Opening a browser to sign in to a site from Settings, where the deployment has one.
 *
 * `available` is false until the deployment says otherwise, so the option is
 * never offered by a deployment that would refuse it.
 */
export function useSignInToSite(): {
  available: boolean;
  start: (url: string) => Promise<SignInSession>;
  isStarting: boolean;
} {
  const { data } = useQuery({ queryKey: qk.browserSignIns.browser(), queryFn: getSignInBrowser });
  const starting = useMutation({ mutationFn: startSignIn });
  return {
    available: data?.available === true,
    start: (url) => starting.mutateAsync(url),
    isStarting: starting.isPending,
  };
}
