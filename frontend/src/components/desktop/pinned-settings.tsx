"use client";

import { PinOff } from "lucide-react";
import { useTranslations } from "next-intl";

import { DesktopOnly } from "@/components/desktop/desktop-only";
import { SectionCard } from "@/components/settings/settings-section";
import { Button } from "@/components/ui";
import { useSetPinned } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";

/**
 * The agents in "New Chat With" (#2305): the Dock icon's menu on macOS and the
 * tray's everywhere, in the order they were pinned. Pinned from an agent's
 * page; taken off here or there.
 */
export function PinnedSettings() {
  const t = useTranslations("desktop.settings.pinned");
  const macos = useShell()?.platform === "macos";
  const setPinned = useSetPinned();
  return (
    <DesktopOnly>
      {({ pinned }) => (
        <SectionCard
          title={t("title")}
          description={macos ? t("descriptionDock") : t("descriptionTray")}
        >
          {pinned.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("empty")}</p>
          ) : (
            <ul className="divide-y">
              {pinned.map((agent) => (
                <li key={agent.id} className="flex items-center justify-between gap-4 py-2.5">
                  <span className="text-foreground min-w-0 truncate text-sm">{agent.name}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={setPinned.isPending}
                    onClick={() => setPinned.mutate({ agent, pinned: false })}
                  >
                    <PinOff className="h-4 w-4" />
                    {t("unpin")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      )}
    </DesktopOnly>
  );
}
