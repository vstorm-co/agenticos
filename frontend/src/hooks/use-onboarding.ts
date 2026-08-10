"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { usePermissions } from "@/hooks/use-permissions";
import { stripLocale } from "@/lib/active-route";
import { apiClient, ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { visibleTourSteps, type TourStep } from "@/lib/onboarding/tour";
import { useAuthStore, useOnboardingStore } from "@/stores";
import type { User } from "@/types";

export interface OnboardingTourState {
  isOpen: boolean;
  steps: readonly TourStep[];
  /** The step currently showing — `steps[index]`, already clamped into range. */
  step: TourStep | undefined;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  next: () => void;
  back: () => void;
  /** Persist completion and close. Finish, Skip and the panel's own dismiss all land here. */
  dismiss: () => void;
}

/**
 * Drives the guided tour: which steps this caller sees, where it opens itself,
 * and how a dismissal is remembered.
 *
 * This is the state half. It owns the step list, the index and how a dismissal
 * is persisted; the imperative browser half — spotlighting an element with
 * driver.js and navigating between pages — lives in `components/onboarding`,
 * which reads `step` from here and never the other way round. Splitting it so
 * keeps this hook pure enough to hold to the 100% gate that `src/hooks/**`
 * carries, and keeps the DOM work out of it.
 *
 * The step list is filtered by permission, so a Viewer's tour is exactly the
 * pages their sidebar shows (`lib/onboarding/tour.ts`). It auto-opens once per
 * page load, but only on `/dashboard` and only for a signed-in user who has not
 * finished onboarding, once the permission set is known and not in error — a
 * returning user, one part-way through another page, or one whose organization
 * the server is refusing (which would collapse the tour to its ungated steps) is
 * left alone. A dismissal from any step writes `onboarding_completed_at` through
 * `PATCH /users/me`, so the tour does not return on the next load or the next
 * device. The panel closes while that write is in flight; a failure is surfaced
 * but not retried, and the flag is left unset, because a walkthrough is not worth
 * trapping someone in.
 */
export function useOnboardingTour(): OnboardingTourState {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const { can, isLoading: permissionsLoading, error: permissionsError } = usePermissions();
  const t = useTranslations("onboarding");
  const { isOpen, index, restart, close, setIndex } = useOnboardingStore();

  const steps = useMemo(() => visibleTourSteps(can), [can]);
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
  // the tour back open and a manual restart is never fought by the effect.
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
    step: steps[clamped],
    index: clamped,
    isFirst: clamped === 0,
    isLast: clamped === lastIndex,
    next,
    back,
    dismiss,
  };
}
