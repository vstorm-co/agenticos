"use client";

import { Server } from "lucide-react";
import { useTranslations } from "next-intl";

import { useChangeServer } from "@/hooks/use-desktop";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { cn } from "@/lib/utils";

/** A server switch stays in reach even when blobby is hidden. */
export function ServerSwitch({ compact = false }: { compact?: boolean }) {
  const shell = useShell();
  return isDesktopShell(shell) && shell.window === "main" ? (
    <ServerSwitchButton compact={compact} />
  ) : null;
}

function ServerSwitchButton({ compact }: { compact: boolean }) {
  const t = useTranslations("desktop.server");
  const change = useChangeServer();
  return (
    <button
      type="button"
      onClick={() => change.mutate()}
      disabled={change.isPending}
      aria-label={t("change")}
      title={t("change")}
      className={cn(
        "text-muted-foreground hover:bg-accent/60 hover:text-foreground focus-visible:ring-ring flex h-9 items-center rounded-md text-xs transition-colors outline-none focus-visible:ring-1 disabled:opacity-50",
        compact ? "w-9 justify-center" : "w-full gap-2 px-2",
      )}
    >
      <Server className="h-4 w-4 shrink-0" aria-hidden />
      {!compact && t("change")}
    </button>
  );
}
