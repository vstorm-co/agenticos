"use client";

import Link from "next/link";
import { ArrowUpRight, Compass } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { useMounted } from "@/hooks/use-mounted";
import { safeStartLocation, startLocationKey } from "@/lib/onboarding/start-location";
import { useOnboardingLocationStore } from "@/stores/onboarding-location-store";
import { useAuthStore, useOrgStore } from "@/stores";

/** Navigation only: completion and reminder preferences remain server-owned. */
export function useOnboardingResume(): {
  userId: string | undefined;
  orgId: string | null;
  href: string;
} {
  const mounted = useMounted();
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const stored = useOnboardingLocationStore((store) =>
    userId && orgId ? store.startLocations[startLocationKey(userId, orgId)] : undefined,
  );
  return {
    userId,
    orgId,
    href: mounted && orgId ? (safeStartLocation(stored, orgId) ?? "/onboarding") : "/onboarding",
  };
}

/** A permanent route back, including when a member disabled sidebar reminders. */
export function OnboardingResumeLink() {
  const t = useTranslations("start.sidebarReminder");
  const { href } = useOnboardingResume();
  return (
    <div className="border-border flex flex-wrap items-center gap-3 border-t py-5">
      <Compass className="text-muted-foreground size-5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 basis-40 space-y-1">
        <h3 className="text-sm font-medium">{t("manualTitle")}</h3>
        <p className="text-muted-foreground text-xs leading-relaxed">{t("manualHint")}</p>
      </div>
      <Button asChild variant="outline" size="sm">
        <Link href={href}>
          {t("manualAction")}
          <ArrowUpRight className="size-3.5" aria-hidden />
        </Link>
      </Button>
    </div>
  );
}
