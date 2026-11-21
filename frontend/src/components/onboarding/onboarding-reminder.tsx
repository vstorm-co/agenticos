"use client";

import { useEffect } from "react";
import Link from "next/link";
import { CircleDashed, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";
import { safeStartLocation, startLocationKey } from "@/lib/onboarding/start-location";
import { useMounted } from "@/hooks/use-mounted";
import { useStart } from "@/hooks/use-start";
import { useAuthStore, useOrgStore } from "@/stores";

/** Completion and the 24-hour snooze belong to this membership, never local UI storage. */
export function OnboardingReminder({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const mounted = useMounted();
  const userId = useAuthStore((state) => state.user?.id);
  const userLoading = useAuthStore((state) => state.isLoading);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const state = useStart(!userLoading);
  const stored = useOnboardingLocationStore((store) =>
    userId && orgId ? store.startLocations[startLocationKey(userId, orgId)] : undefined,
  );
  const href =
    mounted && orgId ? (safeStartLocation(stored, orgId) ?? "/onboarding") : "/onboarding";
  useEffect(() => {
    if (
      userId &&
      orgId &&
      !state.error &&
      state.data?.organization_id === orgId &&
      state.data.completed
    )
      useOnboardingLocationStore.getState().clearStartLocation(userId, orgId);
  }, [userId, orgId, state.error, state.data]);
  const t = useTranslations("start.sidebarReminder");
  if (
    userLoading ||
    state.waitingForScope ||
    state.isLoading ||
    state.error ||
    !state.data ||
    state.data.organization_id !== orgId ||
    state.data.completed
  )
    return null;

  if (collapsed || state.data.dismissed)
    return (
      <Link
        href={href}
        onClick={onNavigate}
        title={collapsed ? t("title") : undefined}
        aria-label={collapsed ? t("title") : undefined}
        className={
          collapsed
            ? "text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 mx-auto mb-1 grid size-9 shrink-0 place-items-center rounded-lg outline-none focus-visible:ring-2"
            : "text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:min-h-11 mx-3 mb-2 flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs outline-none focus-visible:ring-2"
        }
      >
        <CircleDashed className="size-4 shrink-0" aria-hidden />
        {!collapsed && t("title")}
      </Link>
    );

  return (
    <section
      aria-label={t("title")}
      className="border-border/70 bg-muted/35 mx-3 mb-2 shrink-0 rounded-xl border p-3"
    >
      <div className="flex items-start gap-2">
        <Link
          href={href}
          onClick={onNavigate}
          className="focus-visible:ring-ring min-w-0 flex-1 rounded-sm text-sm font-medium outline-none focus-visible:ring-2"
        >
          {t("title")}
        </Link>
        <button
          type="button"
          disabled={state.save.isPending}
          onClick={() => state.save.mutate({ dismissed: true })}
          aria-label={t("snooze")}
          title={t("snooze")}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring touch:min-h-11 touch:min-w-11 -m-1 grid size-7 shrink-0 place-items-center rounded-md outline-none focus-visible:ring-2 disabled:opacity-50"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      <p className="text-muted-foreground mt-1 text-xs leading-relaxed">{t("hint")}</p>
      {state.save.isError && (
        <p role="alert" className="text-destructive mt-2 text-xs">
          {t("saveFailed")}
        </p>
      )}
    </section>
  );
}
