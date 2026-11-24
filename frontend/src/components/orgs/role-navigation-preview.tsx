"use client";

import { useTranslations } from "next-intl";
import { NAV_GROUPS, navItemVisible } from "@/lib/nav-sections";
import type { Permission } from "@/types/permissions";

export function RoleNavigationPreview({
  hiddenItems,
  can,
}: {
  hiddenItems: readonly string[];
  can: (permission: Permission) => boolean;
}) {
  const t = useTranslations("pages.orgs.navigation");
  const nav = useTranslations("nav");
  const groups = NAV_GROUPS.filter((group) => !group.adminOnly)
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => navItemVisible(item, can, hiddenItems)),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <aside aria-label={t("previewTitle")} className="bg-sidebar h-fit rounded-xl border p-4">
      <h3 className="mb-4 text-sm font-medium">{t("previewTitle")}</h3>
      <div className="space-y-4">
        {groups.map((group) => (
          <div key={group.labelKey ?? "main"}>
            {group.labelKey ? (
              <h4 className="text-muted-foreground mb-2 text-xs">{nav(group.labelKey)}</h4>
            ) : null}
            <ul className="space-y-2">
              {group.items.map((item) => (
                <li key={item.labelKey} className="flex items-center gap-2 text-sm">
                  <item.icon className="size-4 shrink-0" aria-hidden />
                  <span>{nav(item.labelKey)}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="text-muted-foreground mt-5 text-xs">{t("previewHint")}</p>
    </aside>
  );
}
