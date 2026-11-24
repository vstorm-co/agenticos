"use client";

import { useTranslations } from "next-intl";

import { DesktopTab } from "@/components/desktop/desktop-only";
import { ReadinessPanel } from "@/components/desktop/readiness-panel";
import { DesktopNotificationSettings } from "@/components/desktop/notification-settings";
import { DeviceSettings } from "@/components/desktop/device-settings";
import { PinnedSettings } from "@/components/desktop/pinned-settings";
import { WindowSettings } from "@/components/desktop/window-settings";
import { SectionHeading } from "@/components/ui";

/**
 * A desktop app tab: shown in the tab row only inside the app (`settings-tabs.ts`).
 * A browser that followed a link here reads one card saying where these
 * settings live rather than one per section.
 */
export default function DesktopAppPage() {
  const t = useTranslations("desktop.settings.window");

  return (
    <div className="space-y-6">
      <SectionHeading title={t("heading")} description={t("headingHint")} />
      <DesktopTab>
        <ReadinessPanel />
        <DesktopNotificationSettings />
        <DeviceSettings />
        <WindowSettings />
        <PinnedSettings />
      </DesktopTab>
    </div>
  );
}
