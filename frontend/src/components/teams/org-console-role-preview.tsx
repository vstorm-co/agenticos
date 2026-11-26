"use client";

import { ChevronDown, Eye } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogTrigger,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui";
import { NAV_GROUPS, presentedNavigation } from "@/lib/nav-sections";
import { OrganizationConsolePreviewPanels } from "./org-console-preview-panels";
import type { ConsolePresentation, ConsoleRoleDefaults } from "@/lib/console-experience-api";
import type { Permission } from "@/types/permissions";
import type { OrgRole } from "@/types/organization";

export function OrganizationConsoleRolePreview({
  selection,
  role,
  can,
  ...panels
}: {
  selection: readonly string[];
  role: OrgRole;
  can: (permission: Permission) => boolean;
  defaults: ConsoleRoleDefaults | undefined;
  presentation: ConsolePresentation;
  managesMcp: boolean;
  managesSkills: boolean;
}) {
  const t = useTranslations("consoleExperience.presentation");
  const preview = useTranslations("consoleExperience.rolePreview");
  const nav = useTranslations("nav");
  const items = presentedNavigation(
    NAV_GROUPS.filter((group) => !group.adminOnly && !group.switcherOnly),
    selection,
  )
    .flatMap((group) => group.items)
    .filter((item) => !item.permission || can(item.permission));
  const navigation = (
    <ul className="mt-4 space-y-1">
      {items.map((item) => (
        <li
          key={item.labelKey}
          className="flex min-w-0 items-center gap-2 rounded-md px-2 py-2 text-sm"
        >
          <item.icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
          {nav(item.labelKey)}
        </li>
      ))}
      {items.length === 0 && (
        <li className="text-muted-foreground text-sm">{preview("emptyNavigation")}</li>
      )}
    </ul>
  );
  return (
    <Dialog>
      <aside
        className="bg-muted/30 min-w-0 self-start rounded-xl border p-4"
        aria-label={t("preview")}
      >
        <h3 className="text-sm font-medium">{t("previewRole", { role: t(`roles.${role}`) })}</h3>
        <p className="text-muted-foreground mt-1 text-xs leading-5">{t("previewHint")}</p>
        {navigation}
        <DialogTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="mt-4 h-auto min-h-11 w-full whitespace-normal"
          >
            <Eye className="size-4 shrink-0" aria-hidden />
            {preview("open")}
          </Button>
        </DialogTrigger>
      </aside>
      <DialogContent className="flex max-h-[90dvh] w-[calc(100%_-_2rem)] flex-col overflow-hidden sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{t("previewRole", { role: t(`roles.${role}`) })}</DialogTitle>
          <DialogDescription>{preview("hint")}</DialogDescription>
        </DialogHeader>
        <div className="@container min-h-0 overflow-y-auto overscroll-contain">
          <div className="grid min-w-0 gap-5 @min-[45rem]:grid-cols-[12rem_minmax(0,1fr)]">
            <section
              aria-label={t("preview")}
              className="bg-muted/30 hidden min-w-0 rounded-xl border p-3 @min-[45rem]:block"
            >
              <h3 className="text-sm font-medium">{preview("navigation")}</h3>
              {navigation}
            </section>
            <details className="bg-muted/30 group min-w-0 rounded-xl border px-3 @min-[45rem]:hidden">
              <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 text-sm font-medium">
                {preview("navigation")}
                <ChevronDown
                  className="size-4 shrink-0 transition-transform group-open:rotate-180"
                  aria-hidden
                />
              </summary>
              {navigation}
            </details>
            <OrganizationConsolePreviewPanels {...panels} role={role} can={can} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
