"use client";

import { Wrench } from "lucide-react";
import { useTranslations } from "next-intl";

import { useBranding } from "@/components/branding/branding-provider";
import { PAGE_CLEARANCE } from "@/lib/page-clearance";
import { cn } from "@/lib/utils";

/**
 * What the product shows while a maintenance window is open.
 *
 * Not the whole of the mechanism, and deliberately the smaller half: the API is
 * already refusing everything outside its allow-list, so without this page a user
 * would get a dashboard of failed queries and error states - the same outage,
 * described worse. This says what is happening and, if the operator wrote one, why.
 *
 * The deployment's own administrator never sees it. They are the one who has to
 * turn the window off, and hiding the console from them is how a maintenance mode
 * becomes an outage.
 */
export function MaintenanceScreen() {
  const t = useTranslations("pages.maintenance");
  const { appName, maintenanceMessage } = useBranding();

  return (
    // The clearance is this one's own because `DeploymentGate` returns it
    // *instead of* rendering `PageTransition`, which is where every other page
    // gets it. Same token, so there is still one answer (#933).
    <div
      className={cn(
        "flex min-h-[60vh] flex-col items-center justify-center px-6 text-center",
        PAGE_CLEARANCE,
      )}
    >
      <span className="bg-muted text-foreground mb-6 inline-flex h-14 w-14 items-center justify-center rounded-2xl">
        <Wrench className="h-6 w-6" aria-hidden />
      </span>
      <h1 className="text-display-md text-foreground mb-3">{t("heading", { app: appName })}</h1>
      <p className="text-muted-foreground max-w-md text-sm leading-relaxed">
        {maintenanceMessage || t("body")}
      </p>
    </div>
  );
}
