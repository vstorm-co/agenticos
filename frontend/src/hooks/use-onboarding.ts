"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { usePermissions } from "@/hooks/use-permissions";
import { stripLocale } from "@/lib/active-route";
import { apiClient, ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { visibleOnboardingSteps, type OnboardingStep } from "@/lib/onboarding/steps";
import { useAuthStore, useOnboardingStore } from "@/stores";
import type { User } from "@/types";

export interface OnboardingTourState {
  isOpen: boolean;
  steps: readonly OnboardingStep[];
  index: number;
  isFirst: boolean;
  isLast: boolean;
  next: () => void;
  back: () => void;
  /** Persist completion and close. Finish, Skip and the dialog's own dismiss all land here. */
  dismiss: () => void;
}

/**
 * Drives the first-run walkthrough: which steps this caller sees, where it opens
 * itself, and how a dismissal is remembered.
 *
 * The step list is filtered by permission, so a Viewer's tour is exactly the
 * pages their sidebar shows (see `lib/onboarding/steps.ts`). The modal
 * auto-opens once per page load, but only on `/dashboard` and only for a signed-in
 * user who has not finished onboarding, once the permission set is known and not
 * in error — a returning user, one part-way through another page, or one whose
 * organization the server is refusing (which would collapse the tour to its
 * ungated steps) is left alone. A dismissal from any step writes
 * `onboarding_completed_at` through `PATCH /users/me`, so the tour does not
 * return on the next load or the next device. The modal closes optimistically
 * while that write is in flight; a failure is surfaced but not retried, and the
 * flag is left unset, because a walkthrough is not worth trapping someone in.
 *
 * Only the modal, mounted once in the dashboard layout, calls this. The restart
 * control reads the store's `restart` directly, so it carries none of the
 * auto-start machinery onto every page it renders on.
 */
export function useOnboardingTour(): OnboardingTourState {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const { can, isLoading: permissionsLoading, error: permissionsError } = usePermissions();
  const t = useTranslations("onboarding");
  const { isOpen, index, restart, close, setIndex } = useOnboardingStore();

  const steps = useMemo(() => visibleOnboardingSteps(can), [can]);
  const lastIndex = steps.length - 1;
  const clamped = Math.min(index, lastIndex);

  const dismiss = useCallback(() => {
    close();
    if (!user || user.onboarding_completed_at) return;
    void (async () => {
      try {
        const updated = await apiClient.patch<User>("/users/me", {
          onboarding_completed_at: new Date().toISOString(),
        });
        setUser(updated);
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : t("saveFailed"));
      }
    })();
  }, [close, user, setUser, t]);

  const next = useCallback(
    () => setIndex(Math.min(clamped + 1, lastIndex)),
    [clamped, lastIndex, setIndex],
  );
  const back = useCallback(() => setIndex(Math.max(clamped - 1, 0)), [clamped, setIndex]);

  // Auto-start fires at most once per page load, so a failed persist cannot loop
  // the modal back open and a manual restart is never fought by the effect.
  const hasAutoStarted = useRef(false);
  const shouldAutoStart =
    stripLocale(pathname) === ROUTES.DASHBOARD &&
    !permissionsLoading &&
    !permissionsError &&
    !!user &&
    !user.onboarding_completed_at;

  useEffect(() => {
    if (shouldAutoStart && !hasAutoStarted.current) {
      hasAutoStarted.current = true;
      restart();
    }
  }, [shouldAutoStart, restart]);

  return {
    isOpen,
    steps,
    index: clamped,
    isFirst: clamped === 0,
    isLast: clamped === lastIndex,
    next,
    back,
    dismiss,
  };
}
