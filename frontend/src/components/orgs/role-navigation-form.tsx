"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useUpdateRoleNavigation } from "@/hooks/use-role-navigation";
import { getErrorMessage } from "@/lib/api-error";
import type { OrgRole } from "@/types/organization";
import type { Permission, RoleCatalog } from "@/types/permissions";
import type { RoleNavigationPolicy } from "@/types/role-navigation";
import { RoleNavigationChoices } from "./role-navigation-choices";
import { RoleNavigationPreview } from "./role-navigation-preview";

export function RoleNavigationForm({
  organizationId,
  catalog,
  policy,
}: {
  organizationId: string;
  catalog: RoleCatalog;
  policy: RoleNavigationPolicy;
}) {
  const t = useTranslations("pages.orgs.navigation");
  const errors = useTranslations("errors");
  const mutation = useUpdateRoleNavigation();
  const [role, setRole] = useState<OrgRole>("member");
  const [draft, setDraft] = useState<string[] | null>(null);
  const stored = policy.hidden_items[role];
  const hiddenItems = draft ?? stored;
  const dirty =
    hiddenItems.length !== stored.length || hiddenItems.some((id) => !stored.includes(id));
  const editable = policy.editable_roles.includes(role);
  const permissions = catalog.roles.find((entry) => entry.name === role)?.permissions ?? [];
  const can = (permission: Permission) =>
    permissions.some((entry) => entry.permission === permission && entry.scope !== "none");

  const change = (next: string[]) => {
    setDraft(next);
    mutation.reset();
  };
  const selectRole = (next: string) => {
    setRole(next as OrgRole);
    setDraft(null);
    mutation.reset();
  };
  const save = () =>
    mutation.mutate({ organizationId, role, hiddenItems }, { onSuccess: () => setDraft(null) });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start gap-4">
        <div className="w-full space-y-2 sm:w-56">
          <label htmlFor="navigation-role" className="text-sm font-medium">
            {t("role")}
          </label>
          <Select value={role} onValueChange={selectRole} disabled={dirty || mutation.isPending}>
            <SelectTrigger id="navigation-role" aria-label={t("role")}>
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
        {!editable ? (
          <p className="text-muted-foreground max-w-lg text-sm sm:pt-7">
            {role === "owner" ? t("ownerProtected") : t("readOnly")}
          </p>
        ) : null}
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_16rem]">
        <RoleNavigationChoices
          hiddenItems={hiddenItems}
          configurableItems={policy.configurable_items}
          can={can}
          disabled={!editable || mutation.isPending}
          onChange={(id, visible) =>
            change(visible ? hiddenItems.filter((item) => item !== id) : [...hiddenItems, id])
          }
        />
        <RoleNavigationPreview hiddenItems={hiddenItems} can={can} />
      </div>

      {mutation.isError ? (
        <p role="alert" className="text-destructive text-sm">
          {getErrorMessage(mutation.error, errors)}
        </p>
      ) : null}
      {editable ? (
        <div className="flex flex-wrap items-center gap-3 border-t pt-4">
          <Button onClick={save} disabled={!dirty} loading={mutation.isPending}>
            {t("save")}
          </Button>
          <Button
            variant="outline"
            onClick={() => change([])}
            disabled={hiddenItems.length === 0 || mutation.isPending}
          >
            {t("reset")}
          </Button>
          {dirty ? (
            <Button
              variant="ghost"
              onClick={() => {
                setDraft(null);
                mutation.reset();
              }}
              disabled={mutation.isPending}
            >
              {t("discard")}
            </Button>
          ) : null}
          <p role="status" className="text-muted-foreground text-xs">
            {dirty ? t("unsaved") : mutation.isSuccess ? t("saved") : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}
