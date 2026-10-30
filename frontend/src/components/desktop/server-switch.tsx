"use client";

import { Server } from "lucide-react";
import { useTranslations } from "next-intl";

import { useChangeServer } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { DropdownMenuItem } from "@/components/ui";

/** The native picker belongs to the main desktop account menu. */
export function ServerSwitch() {
  const shell = useShell();
  return isDesktopShell(shell) && shell.window === "main" ? <ServerSwitchItem /> : null;
}

function ServerSwitchItem() {
  const t = useTranslations("desktop.server");
  const change = useChangeServer();
  return (
    <DropdownMenuItem onSelect={() => change.mutate()} disabled={change.isPending}>
      <Server className="mr-2 h-4 w-4 shrink-0" aria-hidden />
      {t("change")}
    </DropdownMenuItem>
  );
}
