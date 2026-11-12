"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Checkbox, Input, Label } from "@/components/ui";
import {
  routineActionIdentity as identity,
  type RoutineActionOption,
} from "@/lib/routine-actions-api";

export function ActionSelection({
  items,
  selected,
  disabled,
  onChange,
}: {
  items: RoutineActionOption[];
  selected: Set<string>;
  disabled: boolean;
  onChange: (keys: Set<string>) => void;
}) {
  const t = useTranslations("triggers.actionConsents");
  const id = useId();
  const [query, setQuery] = useState("");
  const groups = new Map<string, { name: string; items: RoutineActionOption[] }>();
  for (const action of items) {
    const key =
      "capability_id" in action
        ? `capability:${action.capability_id}`
        : `account:${action.connection_id}`;
    const name =
      "capability_id" in action
        ? action.capability_id
        : t(action.account_scope === "personal" ? "personalAccount" : "organizationAccount", {
            name: action.account_name,
          });
    const group = groups.get(key) ?? { name, items: [] };
    group.items.push(action);
    groups.set(key, group);
  }
  const choose = (actions: RoutineActionOption[], checked: boolean) => {
    const next = new Set(selected);
    for (const action of actions.filter((item) => item.waivable)) {
      if (checked) next.add(identity(action));
      else next.delete(identity(action));
    }
    onChange(next);
  };
  const checked = (actions: RoutineActionOption[]): boolean | "indeterminate" => {
    const eligible = actions.filter((item) => item.waivable);
    const count = eligible.filter((item) => selected.has(identity(item))).length;
    return count === 0 ? false : count === eligible.length ? true : "indeterminate";
  };
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <Label htmlFor={`${id}-search`}>{t("search")}</Label>
        <Input
          id={`${id}-search`}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="flex min-h-11 items-center gap-3">
        <Checkbox
          id={`${id}-all`}
          checked={checked(items)}
          disabled={disabled || !items.some((item) => item.waivable)}
          onCheckedChange={(value) => choose(items, value === true)}
        />
        <Label htmlFor={`${id}-all`} className="flex min-h-11 items-center">
          {t("selectAll")}
        </Label>
      </div>
      <p className="text-muted-foreground text-xs">{t("bulkScope")}</p>
      {[...groups.entries()].map(([key, group], groupIndex) => {
        const shown = group.items.filter((item) =>
          `${group.name} ${item.name}`.toLowerCase().includes(query.trim().toLowerCase()),
        );
        if (!shown.length) return null;
        return (
          <fieldset key={key} className="min-w-0 space-y-2 rounded-lg border p-3">
            <legend className="max-w-full px-1 text-sm font-medium break-words">
              {group.name}
            </legend>
            <div className="flex min-h-11 items-center gap-3">
              <Checkbox
                id={`${id}-group-${groupIndex}`}
                checked={checked(group.items)}
                disabled={disabled || !group.items.some((item) => item.waivable)}
                onCheckedChange={(value) => choose(group.items, value === true)}
              />
              <Label htmlFor={`${id}-group-${groupIndex}`} className="flex min-h-11 items-center">
                {t("selectGroup", { name: group.name })}
              </Label>
            </div>
            {shown.map((action, index) => (
              <div key={identity(action)} className="flex min-h-11 items-center gap-3">
                <Checkbox
                  id={`${id}-${groupIndex}-${index}`}
                  aria-describedby={`${id}-${groupIndex}-${index}-source`}
                  checked={selected.has(identity(action))}
                  disabled={disabled || !action.waivable}
                  onCheckedChange={(value) => choose([action], value === true)}
                />
                <div className="min-w-0 flex-1">
                  <Label
                    className="flex min-h-11 items-center break-all"
                    htmlFor={`${id}-${groupIndex}-${index}`}
                  >
                    {action.name}
                  </Label>
                  <p
                    id={`${id}-${groupIndex}-${index}-source`}
                    className="text-muted-foreground text-xs break-words"
                  >
                    {group.name}
                    {!action.waivable && ` · ${t("required")}`}
                  </p>
                </div>
              </div>
            ))}
          </fieldset>
        );
      })}
      {items.length > 0 &&
        ![...groups.values()].some((group) =>
          group.items.some((item) =>
            `${group.name} ${item.name}`.toLowerCase().includes(query.trim().toLowerCase()),
          ),
        ) && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("noMatches")}
          </p>
        )}
    </div>
  );
}
