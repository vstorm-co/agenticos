"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useReauthenticate } from "@/hooks/use-auth";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores/auth-store";

/**
 * The impersonation this browser is running under, and the one way out of it.
 *
 * Who is acting comes from `/auth/me`, which the auth store already holds: the
 * backend says on every identity read whether somebody else is behind the
 * session, so there is no second request to make and nothing to keep in sync.
 *
 * Ending it is two steps that have to happen in this order. The BFF closes the
 * session row and drops the access cookie; then the identity is re-read, which
 * refreshes from the administrator's own cookie and *adopts* them - clearing
 * the cache and the tenant state that belonged to the account they were acting
 * as (#1044). A refused end is not a reason to stop: the impersonation is over
 * on the backend's side already, and re-reading who we are is the right answer
 * either way.
 *
 * Expiry takes the same path on its own. When the window closes the token would
 * be refused on the next request anyway; taking the exit deliberately means the
 * banner disappears and the administrator lands somewhere that is theirs,
 * rather than on a page of somebody else's that has started answering 404.
 */
export function useImpersonation() {
  const t = useTranslations("layout");
  const router = useRouter();
  const reauthenticate = useReauthenticate();
  const user = useAuthStore((state) => state.user);
  const impersonation = user?.impersonation ?? null;
  const [ending, setEnding] = useState(false);

  const end = useCallback(async () => {
    setEnding(true);
    try {
      await apiClient.delete("/auth/impersonation");
    } catch {
      // Already over - the re-read below says who we are now.
    }
    await reauthenticate();
    setEnding(false);
    toast.success(t("impersonationEnded"));
    router.push(ROUTES.ADMIN_USERS);
  }, [reauthenticate, router, t]);

  const expiresAt = impersonation?.expires_at ?? null;
  useEffect(() => {
    if (expiresAt === null) return;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    const timer = setTimeout(() => void end(), Math.max(0, remaining));
    return () => clearTimeout(timer);
  }, [expiresAt, end]);

  return { impersonation, actingAs: impersonation ? user : null, end, ending };
}
