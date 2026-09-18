"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import { useAdoptSession } from "@/hooks/use-auth";
import { ROUTES } from "@/lib/constants";
import { invitationTokenFrom, pendingLandingFor } from "@/lib/invitation-links";
import { stageInvitation } from "@/lib/invitation-staging";
import type { User } from "@/types";
import { ErrorState } from "@/components/states";
import { Spinner } from "@/components/ui";
import { useTranslations } from "next-intl";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const t = useTranslations("layout");
  const router = useRouter();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  // Through the same door as every other sign-in. This guard wraps the whole
  // dashboard and re-reads `/auth/me` whenever it finds nobody signed in, so
  // after the first auth check it is the only thing in the tab that can learn
  // the identity has changed - and it used to write the answer straight into
  // the store, leaving the previous account's cache under the new one.
  const adoptSession = useAdoptSession();
  const [checking, setChecking] = useState(!isAuthenticated);
  // The invitation token whose staging failed, kept so the retry has it. The URL
  // still carries it too: the guard does not leave the link until the exchange has
  // succeeded, because the token is the only credential the invitee holds.
  const [unstagedToken, setUnstagedToken] = useState<string | null>(null);

  // Exchange the token for an httpOnly-cookie handle before the sign-in detour, so
  // it never rides `returnTo`, browser history or `sessionStorage` (#1414). The
  // landing carries only the flow id; an invalid token is reported there, once there
  // is a session to report to. A staging the server refused - transiently, or with a
  // rate limit - keeps the invitee here to try again rather than sending them to sign
  // in with nothing staged to come back to.
  const stageAndGo = useCallback(
    async (token: string) => {
      const flow = await stageInvitation(token);
      if (flow) {
        setUnstagedToken(null);
        router.replace(`${ROUTES.LOGIN}?returnTo=${encodeURIComponent(pendingLandingFor(flow))}`);
      } else {
        setUnstagedToken(token);
      }
    },
    [router],
  );

  useEffect(() => {
    if (isAuthenticated) return;

    const verify = async () => {
      try {
        const { access_token, ...user } = await apiClient.get<User & { access_token?: string }>(
          "/auth/me",
        );
        adoptSession(user as User, access_token ?? null);
      } catch {
        // Off `window.location`, not the navigation hooks: a hook here would
        // tie the verify effect to every navigation this guard sits above.
        const { pathname, search, hash } = window.location;
        const invitationToken = invitationTokenFrom(pathname);
        if (invitationToken) {
          await stageAndGo(invitationToken);
        } else {
          router.replace(
            `${ROUTES.LOGIN}?returnTo=${encodeURIComponent(pathname + search + hash)}`,
          );
        }
      } finally {
        setChecking(false);
      }
    };

    verify();
  }, [isAuthenticated, router, adoptSession, stageAndGo]);

  const retryStaging = async (token: string) => {
    setChecking(true);
    try {
      await stageAndGo(token);
    } finally {
      setChecking(false);
    }
  };

  if (checking && !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center" role="status" aria-live="polite">
        <Spinner className="text-muted-foreground h-6 w-6" />
        <span className="sr-only">{t("checkingAuthentication")}</span>
      </div>
    );
  }

  if (unstagedToken && !isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <ErrorState
          className="w-full max-w-md"
          title={t("invitationNotStaged")}
          description={t("invitationNotStagedHint")}
          cta={{ label: t("retryInvitation"), onClick: () => void retryStaging(unstagedToken) }}
        />
      </div>
    );
  }

  return <>{children}</>;
}
