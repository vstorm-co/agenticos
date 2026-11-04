"use client";

import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { version } from "../../../package.json";
import { useReleaseUpdate } from "@/hooks/use-release-update";
import { isNewerRelease } from "@/lib/releases";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function ConsoleVersion({ collapsed = false }: { collapsed?: boolean }) {
  const t = useTranslations("nav");
  const { data } = useReleaseUpdate();
  const release = data?.latest;
  const update = release && isNewerRelease(version, release.version) ? release : null;
  const label = t("consoleVersion", { version });
  const classes = cn("font-mono text-[11px] tabular-nums", !collapsed && "ml-auto");
  return (
    <span className={classes}>
      <span role="status" className="sr-only">
        {update ? t("updateAvailable", { version: update.version }) : ""}
      </span>
      {update ? (
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={t("updateAvailable", { version: update.version })}
              title={`${label} · ${t("updateAvailable", { version: update.version })}`}
              className="bg-success/10 text-foreground ring-success/25 focus-visible:ring-ring hover:bg-success/15 relative inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 ring-1 transition-colors outline-none focus-visible:ring-2"
            >
              <span
                className={cn(
                  "bg-success size-1.5 shrink-0 rounded-full",
                  collapsed && "absolute top-0 right-0",
                )}
                aria-hidden
              />
              v{version}
            </button>
          </PopoverTrigger>
          <PopoverContent side="top" align="end" className="w-72 space-y-3 font-sans">
            <h2 className="text-sm font-semibold">{t("updateTitle")}</h2>
            <p className="text-muted-foreground text-sm">
              {t("updateDescription", { current: version, latest: update.version })}
            </p>
            <a
              href={update.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-foreground focus-visible:ring-ring inline-flex min-h-9 items-center gap-1.5 rounded-md text-sm font-medium underline underline-offset-4 outline-none focus-visible:ring-2"
            >
              {t("viewRelease")}
              <ArrowUpRight className="size-4" aria-hidden />
            </a>
          </PopoverContent>
        </Popover>
      ) : (
        <span
          aria-label={label}
          title={label}
          className={cn(
            "text-muted-foreground inline-flex min-h-8 items-center select-all",
            !collapsed && "pr-2",
          )}
        >
          v{version}
        </span>
      )}
    </span>
  );
}
