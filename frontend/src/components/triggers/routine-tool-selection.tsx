"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  routineToolIdentity,
  type RoutineToolOption,
  type RoutineToolSettingValue,
} from "@/lib/routine-tools-api";

export function RoutineToolSelection({
  items,
  selected,
  disabled,
  onChange,
}: {
  items: RoutineToolOption[];
  selected: ReadonlyMap<string, RoutineToolSettingValue>;
  disabled: boolean;
  onChange: (settings: Map<string, RoutineToolSettingValue>) => void;
}) {
  const t = useTranslations("triggers.toolSettings");
  const agents = useTranslations("agents");
  const id = useId();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLocaleLowerCase();
  const groups = new Map<string, { name: string; items: RoutineToolOption[] }>();
  for (const item of items) {
    const [key, name] =
      "capability_id" in item
        ? [`capability:${item.capability_id}`, item.capability_name]
        : "connection_id" in item
          ? [
              `connection:${item.connection_id}`,
              t(item.account_scope === "personal" ? "personalAccount" : "organizationAccount", {
                name: item.account_name,
              }),
            ]
          : [`platform:${item.group}`, agents("platformToolGroup", { group: item.group })];
    if (!`${name} ${item.name}`.toLocaleLowerCase().includes(needle)) continue;
    const group = groups.get(key) ?? { name, items: [] };
    group.items.push(item);
    groups.set(key, group);
  }
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={`${id}-search`}>{t("search")}</Label>
        <Input
          id={`${id}-search`}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <Button
        type="button"
        variant="outline"
        disabled={disabled || selected.size === 0}
        onClick={() => onChange(new Map())}
      >
        {t("reset")}
      </Button>
      {items.length === 0 && <p className="text-muted-foreground text-sm">{t("empty")}</p>}
      {items.length > 0 && groups.size === 0 && (
        <p className="text-muted-foreground text-sm">{t("noMatches")}</p>
      )}
      {[...groups.entries()].map(([groupKey, group]) => (
        <section key={groupKey} className="space-y-2">
          <h3 className="text-sm font-medium">{group.name}</h3>
          <div className="divide-border divide-y rounded-xl border px-3">
            {group.items.map((item) => {
              const identity = routineToolIdentity(item);
              const controlId = `${id}-${identity}`;
              return (
                <div key={identity} className="flex flex-wrap items-center gap-3 py-3">
                  <Label
                    htmlFor={controlId}
                    className="min-w-0 flex-1 basis-40 flex-col items-start space-y-1"
                  >
                    <span className="block break-words">{item.name}</span>
                    <span className="text-muted-foreground block text-xs font-normal">
                      {t(item.agent === "ask" ? "agentAsks" : "agentFree")}
                    </span>
                  </Label>
                  <Select
                    value={selected.get(identity) ?? "follow"}
                    disabled={disabled}
                    onValueChange={(value) => {
                      const next = new Map(selected);
                      if (value === "ask" || value === "off") next.set(identity, value);
                      else next.delete(identity);
                      onChange(next);
                    }}
                  >
                    <SelectTrigger id={controlId} className="w-full sm:w-48">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="follow">{t("follow")}</SelectItem>
                      {item.agent !== "ask" && <SelectItem value="ask">{t("ask")}</SelectItem>}
                      <SelectItem value="off">{t("off")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
