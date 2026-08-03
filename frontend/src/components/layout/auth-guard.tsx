"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import { useAdoptSession } from "@/hooks/use-auth";
import { ROUTES } from "@/lib/constants";
import type { User } from "@/types";
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
        const { pathname, search } = window.location;
        router.replace(`${ROUTES.LOGIN}?returnTo=${encodeURIComponent(pathname + search)}`);
      } finally {
        setChecking(false);
      }
    };

    verify();
  }, [isAuthenticated, router, adoptSession]);

  if (checking && !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center" role="status" aria-live="polite">
        <Spinner className="text-muted-foreground h-6 w-6" />
        <span className="sr-only">{t("checkingAuthentication")}</span>
      </div>
    );
  }

  return <>{children}</>;
}
