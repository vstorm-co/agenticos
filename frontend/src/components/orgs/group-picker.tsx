"use client";

import { useTranslations } from "next-intl";
import { Checkbox, Label } from "@/components/ui";
import { useGroups } from "@/hooks/use-groups";
import { useOrgStore } from "@/stores";

/** Selected missing groups stay removable; their absence never means everyone. */
export function GroupPicker({
  selected,
  onChange,
  disabled,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("approvalGroups");
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "";
  const { groups, error, isLoading } = useGroups(orgId);
  const options = [
    ...groups.map((group) => ({ id: group.id, name: group.name })),
    ...selected
      .filter((id) => !groups.some((group) => group.id === id))
      .map((id) => ({ id, name: id })),
  ];
  return (
    <fieldset className="space-y-2 rounded-lg border p-3" disabled={disabled}>
      <legend className="px-1 text-xs font-medium">{t("groups")}</legend>
      {error ? (
        <p className="text-destructive text-xs">{t("error")}</p>
      ) : isLoading ? (
        <p className="text-muted-foreground text-xs">{t("loading")}</p>
      ) : options.length === 0 ? (
        <p className="text-muted-foreground text-xs">{t("empty")}</p>
      ) : null}
      <div className="max-h-48 space-y-2 overflow-auto">
        {options.map((group) => (
          <Label key={group.id} className="flex items-center gap-2 text-sm font-normal">
            <Checkbox
              disabled={disabled}
              checked={selected.includes(group.id)}
              onCheckedChange={() =>
                onChange(
                  selected.includes(group.id)
                    ? selected.filter((id) => id !== group.id)
                    : [...selected, group.id],
                )
              }
            />
            <span className="truncate">{group.name}</span>
          </Label>
        ))}
      </div>
    </fieldset>
  );
}
