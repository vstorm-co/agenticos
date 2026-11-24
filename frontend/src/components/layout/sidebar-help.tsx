"use client";

import { BookOpen, Bug, CircleHelp, GraduationCap } from "lucide-react";
import { useTranslations } from "next-intl";

import { version } from "../../../package.json";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DOCS_URL, LEARN_URL, reportProblemUrl } from "@/lib/help-links";
import { cn } from "@/lib/utils";

/**
 * The sidebar's Help entry: the docs, the Learn track, and a bug report
 * pre-filled with the running console version.
 *
 * It lives in the sidebar foot, beside the account menu that holds Settings:
 * a stuck user looks at the foot of the column, not among the destinations
 * they use every day. And a link to somewhere else is not a destination - it
 * has no active state and no place in the nav table - so it is not a
 * `NAV_GROUPS` row. One row, opening upward like the version popover beside
 * it, on the desktop column and in the mobile slide-over alike: both render
 * the same shell.
 */
export function SidebarHelp({ collapsed = false }: { collapsed?: boolean }) {
  const t = useTranslations("nav");
  const links = [
    {
      href: DOCS_URL,
      icon: BookOpen,
      label: t("helpDocumentation"),
      hint: t("helpDocumentationHint"),
    },
    {
      href: LEARN_URL,
      icon: GraduationCap,
      label: t("helpLearn"),
      hint: t("helpLearnHint"),
    },
    {
      href: reportProblemUrl(version),
      icon: Bug,
      label: t("helpReportProblem"),
      hint: t("helpReportProblemHint"),
    },
  ];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          // On the rail the label is the only thing naming this entry, so it
          // moves to `title` and `aria-label` rather than disappearing.
          aria-label={collapsed ? t("help") : undefined}
          title={collapsed ? t("help") : undefined}
          className={cn(
            "text-foreground/80 hover:bg-foreground/5 hover:text-foreground focus-visible:ring-ring flex items-center rounded-xl text-sm font-medium transition-colors outline-none focus-visible:ring-2",
            collapsed
              ? "touch:min-h-11 touch:min-w-11 h-9 w-9 justify-center"
              : "h-9 w-full gap-2.5 px-2.5",
          )}
        >
          <CircleHelp className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
          {collapsed ? null : <span className="truncate">{t("help")}</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-72 space-y-3">
        <h2 className="text-sm font-semibold">{t("help")}</h2>
        <div className="flex flex-col gap-0.5">
          {links.map(({ href, icon: Icon, label, hint }) => (
            <a
              key={href}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:bg-foreground/5 focus-visible:ring-ring flex items-start gap-2.5 rounded-xl px-2.5 py-2 outline-none focus-visible:ring-2"
            >
              <Icon className="mt-0.5 h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
              <span className="min-w-0">
                <span className="text-foreground block text-sm font-medium">{label}</span>
                <span className="text-muted-foreground block text-xs">{hint}</span>
              </span>
            </a>
          ))}
        </div>
        <p className="text-muted-foreground px-2.5 text-xs">
          {t("helpReportVersion", { version: `v${version}` })}
        </p>
      </PopoverContent>
    </Popover>
  );
}
