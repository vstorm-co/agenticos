"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
 * as (#1044). The BFF answers success for an impersonation that is over
 * already, so a refusal here is a failure to end one that is still on: the
 * administrator stays where they are and is told, rather than being walked to
 * a page the account they are still acting as cannot open.
 *
 * Two things take the exit without a click. The window closing, because the
 * token would be refused on the next request anyway and a deliberate exit
 * lands the administrator on a page that is theirs rather than on somebody
 * else's that has started answering 404. And a refresh the BFF refused because
 * the cookie was an impersonation that had ended - revoked from elsewhere, or
 * lapsed - which the API client reports on the store, since it must not replay
 * the refused request as the administrator.
 */
export function useImpersonation() {
  const t = useTranslations("layout");
  const router = useRouter();
  const reauthenticate = useReauthenticate();
  const user = useAuthStore((state) => state.user);
  const revoked = useAuthStore((state) => state.impersonationRevoked);
  const setRevoked = useAuthStore((state) => state.setImpersonationRevoked);
  const impersonation = user?.impersonation ?? null;
  const [ending, setEnding] = useState(false);
  // The exit can be asked for from three places at once - the button, the
  // expiry timer, a refused refresh - and must run once.
  const inFlight = useRef(false);

  const end = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setEnding(true);
    let ended = false;
    try {
      await apiClient.delete("/auth/impersonation");
      ended = true;
    } catch {
      toast.error(t("impersonationEndFailed"));
    }
    if (ended) {
      await reauthenticate();
      toast.success(t("impersonationEnded"));
      router.push(ROUTES.ADMIN_USERS);
    }
    inFlight.current = false;
    setEnding(false);
  }, [reauthenticate, router, t]);

  const expiresAt = impersonation?.expires_at ?? null;
  useEffect(() => {
    if (expiresAt === null) return;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    const timer = setTimeout(() => void end(), Math.max(0, remaining));
    return () => clearTimeout(timer);
  }, [expiresAt, end]);

  useEffect(() => {
    if (!revoked) return;
    setRevoked(false);
    if (impersonation) void end();
  }, [revoked, impersonation, end, setRevoked]);

  return { impersonation, actingAs: impersonation ? user : null, end, ending };
}
