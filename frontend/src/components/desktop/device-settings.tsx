"use client";

import { LocalServiceSettings } from "./local-service-settings";

import { Laptop, Link2, Unlink } from "lucide-react";
import { useTranslations } from "next-intl";

import { DesktopOnly } from "@/components/desktop/desktop-only";
import { SectionCard } from "@/components/settings/settings-section";
import { Badge, Button } from "@/components/ui";
import { useDeviceLink, useDeviceStatus } from "@/hooks/use-desktop";

/**
 * This computer as a place the person's own agents can work (#2305): linked once,
 * then reachable whenever the app runs. What it may do is chosen per chat - the
 * folder and the mode - so this card only says whether the door is there.
 */
export function DeviceSettings() {
  const t = useTranslations("desktop.settings.device");
  const { data: status } = useDeviceStatus();
  const { link, unlink } = useDeviceLink();
  return (
    <DesktopOnly>
      {() => (
        <>
          <SectionCard title={t("title")} description={t("description")}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-foreground flex items-center gap-2 text-sm">
                <Laptop className="text-muted-foreground h-4 w-4" aria-hidden />
                {!status?.linked
                  ? t("notLinked")
                  : status.connected
                    ? t("connected")
                    : t("reconnecting")}
                {status?.linked && status.connected && (
                  <Badge variant="secondary">{t("live")}</Badge>
                )}
              </span>
              {status?.linked ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={unlink.isPending}
                  onClick={() => unlink.mutate()}
                >
                  <Unlink className="h-4 w-4" />
                  {t("unlink")}
                </Button>
              ) : (
                <Button size="sm" disabled={link.isPending} onClick={() => link.mutate()}>
                  <Link2 className="h-4 w-4" />
                  {t("link")}
                </Button>
              )}
            </div>
          </SectionCard>
          <LocalServiceSettings />
        </>
      )}
    </DesktopOnly>
  );
}
