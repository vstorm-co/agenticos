"use client";

import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { useBranding } from "@/components/branding/branding-provider";
import { Button } from "@/components/ui/button";
import { useAppUpdate } from "@/hooks/use-app-update";

/** A persistent top notch, matching the deployment notice in ServerOS. */
export function AppUpdateBanner() {
  const available = useAppUpdate();
  const t = useTranslations("appUpdate");
  const { appName } = useBranding();

  if (!available) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 top-[var(--shell-inset-top,0px)] z-[100] flex justify-center px-6">
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="bg-foreground text-background before:bg-foreground after:bg-foreground pointer-events-auto relative flex max-w-[560px] items-center gap-3 rounded-b-[20px] px-5 py-2.5 shadow-lg before:absolute before:top-0 before:-left-3 before:size-3 before:[mask-image:radial-gradient(circle_at_0_100%,transparent_12px,#000_12.5px)] after:absolute after:top-0 after:-right-3 after:size-3 after:[mask-image:radial-gradient(circle_at_100%_100%,transparent_12px,#000_12.5px)]"
      >
        <RefreshCw className="size-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("title", { appName })}</p>
          <p className="text-xs opacity-70">{t("description")}</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="bg-background/15 text-background hover:bg-background/25 hover:text-background active:bg-background/30 focus-visible:outline-background/70 ml-1 shrink-0 rounded-full"
          onClick={() => window.location.reload()}
        >
          {t("reload")}
        </Button>
      </div>
    </div>
  );
}
