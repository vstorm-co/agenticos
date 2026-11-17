"use client";

import { useTranslations } from "next-intl";
import { Checkbox } from "@/components/ui";
import { NAV_GROUPS, navItemVisible } from "@/lib/nav-sections";
import type { Permission } from "@/types/permissions";

export function RoleNavigationChoices({
  hiddenItems,
  configurableItems,
  can,
  disabled,
  onChange,
}: {
  hiddenItems: readonly string[];
  configurableItems: readonly string[];
  can: (permission: Permission) => boolean;
  disabled: boolean;
  onChange: (id: string, visible: boolean) => void;
}) {
  const t = useTranslations("pages.orgs.navigation");
  const nav = useTranslations("nav");

  return (
    <div className="min-w-0 space-y-4" aria-label={t("controlsTitle")}>
      <div className="grid gap-4 sm:grid-cols-2">
        {NAV_GROUPS.filter((group) => !group.adminOnly).map((group) => (
          <fieldset
            key={group.labelKey ?? "main"}
            className="min-w-0 space-y-3 rounded-xl border p-4"
          >
            <legend className="px-1 text-sm font-medium">
              {group.labelKey ? nav(group.labelKey) : t("general")}
            </legend>
            {group.items.map((item) => {
              const available = navItemVisible(item, can);
              const configurable = configurableItems.includes(item.labelKey);
              const checked = available && (!configurable || !hiddenItems.includes(item.labelKey));
              const id = `role-navigation-${item.labelKey}`;
              return (
                <div key={item.labelKey} className="flex items-start gap-3">
                  <Checkbox
                    id={id}
                    aria-label={t("showItem", { item: nav(item.labelKey) })}
                    aria-describedby={`${id}-hint`}
                    checked={checked}
                    disabled={disabled || !available || !configurable}
                    onCheckedChange={(value) => onChange(item.labelKey, value === true)}
                    className="mt-0.5"
                  />
                  <div className="min-w-0">
                    <label htmlFor={id} className="text-sm">
                      {nav(item.labelKey)}
                    </label>
                    <p id={`${id}-hint`} className="text-muted-foreground text-xs">
                      {!available
                        ? t("permissionUnavailable")
                        : !configurable
                          ? t("alwaysShown")
                          : checked
                            ? t("visible")
                            : t("hidden")}
                    </p>
                  </div>
                </div>
              );
            })}
          </fieldset>
        ))}
      </div>
    </div>
  );
}
