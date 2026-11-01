"use client";

import { ListChecks } from "lucide-react";
import { useTranslations } from "next-intl";
import { DropdownMenuItem } from "@/components/ui";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";

export const OPEN_DESKTOP_SETUP = "agenticos:open-desktop-setup";

/** Opens the existing connection checklist without navigating away from a draft. */
export function DesktopSetupMenuItem() {
  const shell = useShell();
  const t = useTranslations("desktop.readiness");
  if (!isDesktopShell(shell) || shell.window !== "main") return null;
  return (
    <DropdownMenuItem onSelect={() => window.dispatchEvent(new Event(OPEN_DESKTOP_SETUP))}>
      <ListChecks className="mr-2 h-4 w-4 shrink-0" aria-hidden />
      {t("title")}
    </DropdownMenuItem>
  );
}
