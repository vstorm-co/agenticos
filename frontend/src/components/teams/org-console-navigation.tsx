"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { usePermissions, useRoleCatalog } from "@/hooks/use-permissions";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { widgetCatalog } from "@/lib/dashboard/preference";
import { OrganizationConsoleDashboard } from "./org-console-dashboard";
import { ConsoleCatalogControls } from "@/components/settings/console-catalog-controls";
import { ConsoleNavigationControls } from "@/components/settings/console-navigation-controls";
import { NAV_GROUPS, presentedNavigation } from "@/lib/nav-sections";
import type { ConsolePresentation, ConsoleRoleDefaults } from "@/lib/console-experience-api";
import type { Permission } from "@/types/permissions";
import type { OrgRole } from "@/types/organization";

/** A data-free presentation preview, using the catalog and the caller's own ceiling. */
export function OrganizationConsoleNavigation({
  defaults,
  presentation,
  disabled,
  onSave,
}: {
  defaults: Partial<Record<OrgRole, ConsoleRoleDefaults>> | undefined;
  presentation: ConsolePresentation;
  disabled: boolean;
  onSave: (role: OrgRole, changes: ConsoleRoleDefaults, onSaved: () => void) => void;
}) {
  const id = useId();
  const t = useTranslations("consoleExperience.presentation");
  const nav = useTranslations("nav");
  const catalogs = useTranslations("consoleExperience.catalogs");
  const [role, setRole] = useState<OrgRole>("member");
  const [navDirty, setDirty] = useState(false);
  const [mcpDirty, setMcpDirty] = useState(false);
  const [skillDirty, setSkillDirty] = useState(false);
  const [dashboardDirty, setDashboardDirty] = useState(false);
  const dirty = navDirty || mcpDirty || skillDirty || dashboardDirty;
  const { catalog, isLoading, error } = useRoleCatalog();
  const { can } = usePermissions();
  if (isLoading) return <LoadingState variant="pending" />;
  if (error || !catalog) return <ErrorState />;
  const target = catalog.roles.find((entry) => entry.name === role);
  const managesMcp = target?.permissions.some(
    (entry) => entry.permission === "mcp:manage" && entry.scope !== "none",
  );
  const managesSkills = target?.permissions.some(
    (entry) =>
      entry.permission === "skills:edit" && ["shared", "team", "all"].includes(entry.scope),
  );
  const previewCan = (permission: Permission) =>
    can(permission) &&
    !!target?.permissions.some(
      (entry) => entry.permission === permission && entry.scope !== "none",
    );
  return (
    <div className="space-y-4">
      <div className="max-w-sm space-y-2" data-tour="organization-console-navigation">
        <Label htmlFor={id}>{t("role")}</Label>
        <Select
          value={role}
          disabled={disabled || dirty}
          onValueChange={(next) => {
            const found = catalog.roles.find((item) => item.name === next);
            if (found) setRole(found.name);
          }}
        >
          <SelectTrigger id={id}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {catalog.roles.map((entry) => (
              <SelectItem key={entry.name} value={entry.name}>
                {t(`roles.${entry.name}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {dirty && <p className="text-muted-foreground text-xs">{t("saveBeforeRole")}</p>}
      <ConsoleNavigationControls
        key={role}
        onDirtyChange={setDirty}
        value={defaults?.[role]?.navigation}
        allowed={presentation.navigation_available}
        inherited={presentation.navigation_base_default}
        simple={presentation.simple_navigation}
        disabled={disabled}
        onSave={(navigation, onSaved) => onSave(role, { navigation }, onSaved)}
        preview={(selection) => (
          <aside className="bg-muted/30 self-start rounded-xl border p-4" aria-label={t("preview")}>
            <h3 className="text-sm font-medium">
              {t("previewRole", { role: t(`roles.${role}`) })}
            </h3>
            <p className="text-muted-foreground mt-1 text-xs leading-5">{t("previewHint")}</p>
            <ul className="mt-4 space-y-1">
              {presentedNavigation(
                NAV_GROUPS.filter((group) => !group.adminOnly && !group.switcherOnly),
                selection,
              )
                .flatMap((group) => group.items)
                .filter((item) => !item.permission || previewCan(item.permission))
                .map((item) => (
                  <li
                    key={item.labelKey}
                    className="flex items-center gap-2 rounded-md px-2 py-2 text-sm"
                  >
                    <item.icon className="text-muted-foreground size-4" aria-hidden />
                    {nav(item.labelKey)}
                  </li>
                ))}
            </ul>
          </aside>
        )}
      />
      {managesMcp ? (
        <p className="text-muted-foreground text-xs">
          {catalogs("mcp_gallery")}: {catalogs("managerHint")}
        </p>
      ) : (
        <ConsoleCatalogControls
          key={`${role}-mcp`}
          kind="mcp_gallery"
          value={defaults?.[role]?.mcp_gallery}
          disabled={disabled}
          onDirtyChange={setMcpDirty}
          onSave={(mcp_gallery, onSaved) => onSave(role, { mcp_gallery }, onSaved)}
        />
      )}
      {managesSkills ? (
        <p className="text-muted-foreground text-xs">
          {catalogs("skill_gallery")}: {catalogs("managerHint")}
        </p>
      ) : (
        <ConsoleCatalogControls
          key={`${role}-skills`}
          kind="skill_gallery"
          value={defaults?.[role]?.skill_gallery}
          disabled={disabled}
          onDirtyChange={setSkillDirty}
          onSave={(skill_gallery, onSaved) => onSave(role, { skill_gallery }, onSaved)}
        />
      )}
      <OrganizationConsoleDashboard
        key={`${role}-dashboard`}
        value={defaults?.[role]?.dashboard}
        catalog={widgetCatalog(previewCan, false)}
        disabled={disabled}
        onDirtyChange={setDashboardDirty}
        onSave={(dashboard, onSaved) => onSave(role, { dashboard }, onSaved)}
      />
    </div>
  );
}
