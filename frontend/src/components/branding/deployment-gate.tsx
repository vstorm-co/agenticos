"use client";

import type { ReactNode } from "react";
import { Wrench } from "lucide-react";
import { useTranslations } from "next-intl";

import { AnnouncementBanner } from "@/components/branding/announcement-banner";
import { useBranding } from "@/components/branding/branding-provider";
import { MaintenanceScreen } from "@/components/branding/maintenance-screen";
import { useAuth } from "@/hooks";

/**
 * What the deployment's own state does to the page under it.
 *
 * Two things, and they are here together because both are answers to "what is
 * true of this installation right now" rather than of any one page: the
 * administrator's announcement, and a maintenance window.
 *
 * The window hides the product from everybody **except** the deployment's
 * administrator, who gets a strip instead. They are the only person who can turn
 * it off, and a maintenance mode that also hides the switch is an outage. The API
 * agrees with that split on its own terms - the admin endpoints are on its allow-list
 * - so this is the same rule drawn rather than a second, looser one.
 */
export function DeploymentGate({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.maintenance");
  const { maintenanceMode } = useBranding();
  const { user } = useAuth();

  if (maintenanceMode && !user?.is_app_admin) {
    return <MaintenanceScreen />;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {maintenanceMode && (
        <div
          role="status"
          className="border-warning/40 bg-warning/10 text-foreground flex items-center gap-2.5 rounded-xl border px-4 py-2.5 text-sm"
        >
          <Wrench className="h-4 w-4 shrink-0" aria-hidden />
          <p>{t("adminStrip")}</p>
        </div>
      )}
      <AnnouncementBanner enabled={Boolean(user)} />
      {children}
    </div>
  );
}
