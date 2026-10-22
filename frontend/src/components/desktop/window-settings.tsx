"use client";

import { useTranslations } from "next-intl";

import { DesktopOnly, DesktopSetting } from "@/components/desktop/desktop-only";
import { SectionCard } from "@/components/settings/settings-section";
import { Switch } from "@/components/ui/switch";
import { useSetWindowPreferences } from "@/hooks/use-desktop";
import type { WindowPreferences } from "@/lib/desktop/commands";

const ROWS: readonly (keyof WindowPreferences)[] = ["launch_at_login", "keep_running", "badge"];

/**
 * How the desktop app behaves as an application: whether it opens at login,
 * whether closing its window quits it or leaves it in the menu bar, and whether
 * the Dock icon counts what is waiting.
 */
export function WindowSettings() {
  const t = useTranslations("desktop.settings.window");
  const change = useSetWindowPreferences();
  return (
    <DesktopOnly>
      {({ window }) => (
        <SectionCard title={t("title")} description={t("description")}>
          <div className="space-y-5">
            {ROWS.map((row) => (
              <DesktopSetting
                key={row}
                id={`window-${row}`}
                label={t(`${row}.label`)}
                hint={t(`${row}.hint`)}
              >
                <Switch
                  aria-labelledby={`window-${row}`}
                  checked={window[row]}
                  disabled={change.isPending}
                  onCheckedChange={(checked) => change.mutate({ ...window, [row]: checked })}
                />
              </DesktopSetting>
            ))}
          </div>
        </SectionCard>
      )}
    </DesktopOnly>
  );
}
