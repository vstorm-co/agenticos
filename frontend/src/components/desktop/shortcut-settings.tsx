"use client";

import { useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";

import { DesktopOnly, DesktopSetting } from "@/components/desktop/desktop-only";
import { SectionCard } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { useSetShortcut } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import { acceleratorOf, describeAccelerator } from "@/lib/desktop/accelerator";
import type { ShortcutBinding } from "@/lib/desktop/commands";

/**
 * One global shortcut: a field that records the next combination pressed in it,
 * Save to bind it and Clear to switch it off. A combination another application
 * already holds is refused by the app, and the old binding stays.
 */
function ShortcutRow({ binding, mac }: { binding: ShortcutBinding; mac: boolean }) {
  const t = useTranslations("desktop.settings.shortcuts");
  const change = useSetShortcut();
  const [recorded, setRecorded] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const id = `shortcut-${binding.action}`;
  const shown = recorded ?? binding.accelerator;

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Tab") return;
    event.preventDefault();
    if (event.key === "Escape") {
      setRecorded(null);
      event.currentTarget.blur();
      return;
    }
    const accelerator = acceleratorOf(event);
    if (accelerator) setRecorded(accelerator);
  };

  const save = (accelerator: string | null) =>
    change.mutate({ action: binding.action, accelerator }, { onSuccess: () => setRecorded(null) });

  return (
    <DesktopSetting id={id} label={t(`${binding.action}.label`)} hint={t(`${binding.action}.hint`)}>
      <div className="flex flex-col items-end gap-1.5">
        <div className="flex items-center gap-2">
          <input
            aria-labelledby={id}
            readOnly
            value={describeAccelerator(shown, mac)}
            placeholder={recording ? t("press") : t("notBound")}
            onFocus={() => setRecording(true)}
            onBlur={() => setRecording(false)}
            onKeyDown={onKeyDown}
            className="border-input bg-background focus-visible:ring-ring h-8 w-36 cursor-pointer rounded-md border px-2.5 text-center font-mono text-sm outline-none focus-visible:ring-2"
          />
          <Button
            size="sm"
            disabled={recorded === null || recorded === binding.accelerator || change.isPending}
            onClick={() => save(recorded)}
          >
            {t("save")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={binding.accelerator === null || change.isPending}
            onClick={() => save(null)}
          >
            {t("clear")}
          </Button>
        </div>
        {binding.problem ? (
          <p role="alert" className="text-destructive text-xs">
            {t("taken", { accelerator: describeAccelerator(binding.accelerator, mac) })}
          </p>
        ) : null}
      </div>
    </DesktopSetting>
  );
}

/** The desktop app's global shortcuts: they work whichever application is in front. */
export function ShortcutSettings() {
  const t = useTranslations("desktop.settings.shortcuts");
  const mac = useShell()?.platform === "macos";
  return (
    <DesktopOnly>
      {({ shortcuts }) => (
        <SectionCard title={t("title")} description={t("description")}>
          <div className="space-y-5">
            {shortcuts.map((binding) => (
              <ShortcutRow key={binding.action} binding={binding} mac={mac} />
            ))}
          </div>
        </SectionCard>
      )}
    </DesktopOnly>
  );
}
