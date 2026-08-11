"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { usePermissions } from "@/hooks/use-permissions";
import { stripLocale } from "@/lib/active-route";
import { apiClient, ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { stepsForPage, visibleTourSteps, type TourStep } from "@/lib/onboarding/tour";
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
  /** Close, and — only for the first-run tour — persist that onboarding is done. */
  dismiss: () => void;
}

/**
 * Drives the guided tour: which steps this caller sees, where it opens itself,
 * and how a dismissal is remembered.
 *
 * This is the state half. It owns the step list, the index and how a dismissal
 * is persisted; the imperative browser half — the driver.js popover and
 * navigating between pages — lives in `components/onboarding`, which reads `step`
 * from here and never the other way round. Splitting it so keeps this hook pure
 * enough to hold to the 100% gate that `src/hooks/**` carries.
 *
 * In `"tour"` mode the step list is the whole product, permission-filtered, so a
 * Viewer's tour is exactly the pages their sidebar shows; in `"page"` mode it is
 * only the current page's highlights, which is what the header "?" replays. The
 * tour auto-opens once per page load, but only on `/dashboard` and only for a
 * signed-in user who has not finished onboarding, once the permission set is
 * known and not in error — a returning user, one part-way through another page,
 * or one whose organization the server is refusing (which would collapse the
 * tour to its ungated steps) is left alone.
 *
 * Dismissing the first-run tour writes `onboarding_completed_at` through
 * `PATCH /users/me`, so it does not return on the next load or the next device;
 * dismissing a `"page"` replay writes nothing, because asking for help is not
 * finishing onboarding. The panel closes while any write is in flight; a failure
 * is surfaced but not retried, and the flag is left unset, because a walkthrough
 * is not worth trapping someone in.
 */
export function useOnboardingTour(): OnboardingTourState {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const { can, isLoading: permissionsLoading, error: permissionsError } = usePermissions();
  const t = useTranslations("onboarding");
  const { isOpen, index, mode, openTour, close, setIndex } = useOnboardingStore();

  const path = stripLocale(pathname);

  // Freeze the page a "?" replay was opened on. Its walk steps into detail views
  // (the builder, a collection, an organization), and recomputing the step list
  // from the new pathname mid-walk would swap the array out from under the index
  // — the step showing would jump to whatever now sits at that position, or the
  // walk would end with nothing left on the arrived-at page. The anchor is set
  // once, on opening in page mode, and cleared on close so the next "?" anchors
  // wherever it is opened; navigation only fires once the engine advances into a
  // detail step, which is after this effect has run, so the anchor is always in
  // hand before the path moves. The first-run tour needs none of this: its list
  // is permission-filtered, not path-derived, so navigation never changes it.
  const [anchor, setAnchor] = useState<string | null>(null);
  // React's "adjust state while rendering" pattern, not an effect: the guards
  // make each branch fire at most once, so there is no loop and no extra commit.
  if (isOpen && mode === "page" && anchor === null) {
    setAnchor(path);
  } else if (!isOpen && anchor !== null) {
    setAnchor(null);
  }

  const steps = useMemo(
    () => (mode === "page" ? stepsForPage(anchor ?? path, can) : visibleTourSteps(can)),
    [mode, anchor, path, can],
  );
  const lastIndex = steps.length - 1;
  const clamped = Math.min(index, Math.max(lastIndex, 0));

  // A "?" opened on a page with no walkable steps — one with no highlights, or one
  // whose highlights a permission filtered to none — must not stay open: the engine
  // finds no step, tears the popover down, and nothing is left to close the walk, so
  // `anchor` freezes on that page and every later "?" recomputes the same empty list.
  // The help button goes dead app-wide until a reload. Closing it here keeps the
  // anchor clearing and the button live; the first-run tour never reaches this, its
  // list being permission-filtered but never empty. Not while permissions are still
  // loading, though: `can` answers false throughout that window, so every page reads
  // as empty until it settles, and closing then would shut a walk that is about to
  // have steps.
  useEffect(() => {
    if (isOpen && !permissionsLoading && steps.length === 0) close();
  }, [isOpen, permissionsLoading, steps.length, close]);

  const dismiss = useCallback(() => {
    close();
    // A "?" replay is help, not the first run: closing it records nothing.
    if (mode !== "tour" || !user || user.onboarding_completed_at) return;
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
  }, [close, mode, user, setUser, t]);

  const next = useCallback(
    () => setIndex(Math.min(clamped + 1, lastIndex)),
    [clamped, lastIndex, setIndex],
  );
  const back = useCallback(() => setIndex(Math.max(clamped - 1, 0)), [clamped, setIndex]);

  // Auto-start fires at most once per page load, so a failed persist cannot loop
  // the tour back open and a manual restart is never fought by the effect.
  const hasAutoStarted = useRef(false);
  const shouldAutoStart =
    path === ROUTES.DASHBOARD &&
    !permissionsLoading &&
    !permissionsError &&
    !!user &&
    !user.onboarding_completed_at;

  useEffect(() => {
    if (shouldAutoStart && !hasAutoStarted.current) {
      hasAutoStarted.current = true;
      openTour();
    }
  }, [shouldAutoStart, openTour]);

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
