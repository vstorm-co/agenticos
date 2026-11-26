"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { useBranding } from "@/components/branding/branding-provider";
import {
  Button,
  Checkbox,
  Input,
  Label,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
import {
  routineActionIdentity as identity,
  type RoutineActionOption,
} from "@/lib/routine-actions-api";

interface Group {
  name: string | null;
  items: RoutineActionOption[];
}
interface Section {
  name: string;
  groups: Map<string, Group>;
}

/**
 * Routine-specific standing permissions, grouped by capability and MCP account.
 * Required agent/platform gates stay visible and locked; bulk selection covers
 * only eligible tools, including eligible matches hidden by the search.
 */
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
  const agents = useTranslations("agents");
  const { appName } = useBranding();
  const id = useId();
  const [query, setQuery] = useState("");
  const eligible = items.filter((item) => item.waivable);
  const sections = new Map<string, Section>();
  for (const action of items) {
    const [sectionKey, sectionName, groupKey, groupName] =
      "capability_id" in action
        ? [
            "capabilities",
            t("capabilitiesSection"),
            action.capability_id,
            action.capability_name ?? action.capability_id,
          ]
        : "kind" in action
          ? [
              "platform",
              appName,
              action.group,
              agents("platformToolGroup", { group: action.group }),
            ]
          : [
              `account:${action.connection_id}`,
              t(action.account_scope === "personal" ? "personalAccount" : "organizationAccount", {
                name: action.account_name,
              }),
              "",
              null,
            ];
    const section = sections.get(sectionKey) ?? { name: sectionName, groups: new Map() };
    const group = section.groups.get(groupKey) ?? { name: groupName, items: [] };
    group.items.push(action);
    section.groups.set(groupKey, group);
    sections.set(sectionKey, section);
  }
  const needle = query.trim().toLowerCase();
  const matches = (section: Section, group: Group, action: RoutineActionOption) =>
    `${section.name} ${group.name ?? ""} ${action.name}`.toLowerCase().includes(needle);
  const choose = (actions: RoutineActionOption[], checked: boolean) => {
    const next = new Set(selected);
    for (const action of actions.filter((item) => item.waivable)) {
      if (checked) next.add(identity(action));
      else next.delete(identity(action));
    }
    onChange(next);
  };
  const count = (actions: RoutineActionOption[]) =>
    actions.filter((item) => selected.has(identity(item))).length;
  const checked = (actions: RoutineActionOption[]): boolean | "indeterminate" => {
    const chosen = count(actions);
    return chosen === 0 ? false : chosen === actions.length ? true : "indeterminate";
  };
  const shown = [...sections.entries()].flatMap(([sectionKey, section]) => {
    const groups = [...section.groups.entries()]
      .map(([groupKey, group]) => ({
        groupKey,
        group,
        items: group.items.filter((action) => matches(section, group, action)),
      }))
      .filter(({ items: matching }) => matching.length > 0);
    return groups.length ? [{ sectionKey, section, groups }] : [];
  });
  const toggle = (key: string, label: string, actions: RoutineActionOption[]) => (
    <div className="flex min-h-11 items-center gap-3">
      <Checkbox
        id={key}
        checked={checked(actions.filter((action) => action.waivable))}
        disabled={disabled || !actions.some((action) => action.waivable)}
        onCheckedChange={(value) => choose(actions, value === true)}
      />
      <Label htmlFor={key} className="flex min-h-11 flex-1 items-center break-words">
        {t("selectGroup", { name: label })}
      </Label>
      <span className="text-muted-foreground text-xs tabular-nums">
        {t("groupCount", {
          selected: count(actions),
          total: actions.filter((action) => action.waivable).length,
        })}
      </span>
    </div>
  );
  if (items.length === 0) return null;
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
      {/* Its own provider: the dialog opens from places that mount none. */}
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="outline"
              disabled={disabled}
              onClick={() => onChange(new Set(eligible.map(identity)))}
            >
              {t("useAgent")}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("useAgentHint")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <h3 className="text-sm font-medium">{t("allowHeading")}</h3>
      {shown.map(({ sectionKey, section, groups }, sectionIndex) => {
        const all = [...section.groups.values()].flatMap((group) => group.items);
        return (
          <section
            key={sectionKey}
            aria-label={section.name}
            className="min-w-0 space-y-3 rounded-lg border p-3"
          >
            <h4
              id={`${id}-section-${sectionIndex}-name`}
              className="text-sm font-semibold break-words"
            >
              {section.name}
            </h4>
            {toggle(`${id}-section-${sectionIndex}`, section.name, all)}
            {groups.map(({ groupKey, group, items: matching }, groupIndex) => (
              <fieldset key={groupKey} className="min-w-0 space-y-1 border-l pl-3">
                {group.name !== null && (
                  <>
                    <legend
                      id={`${id}-${sectionIndex}-${groupIndex}-name`}
                      className="text-sm font-medium break-words"
                    >
                      {group.name}
                    </legend>
                    {toggle(`${id}-${sectionIndex}-${groupIndex}`, group.name, group.items)}
                  </>
                )}
                {matching.map((action, index) => (
                  <div key={identity(action)} className="flex min-h-11 items-center gap-3">
                    <Checkbox
                      id={`${id}-${sectionIndex}-${groupIndex}-${index}`}
                      // Two accounts can offer the same action name; this says whose it is.
                      aria-describedby={[
                        `${id}-section-${sectionIndex}-name`,
                        ...(group.name === null
                          ? []
                          : [`${id}-${sectionIndex}-${groupIndex}-name`]),
                      ].join(" ")}
                      checked={selected.has(identity(action))}
                      disabled={disabled || !action.waivable}
                      onCheckedChange={(value) => choose([action], value === true)}
                    />
                    <Label
                      className="flex min-h-11 items-center break-all"
                      htmlFor={`${id}-${sectionIndex}-${groupIndex}-${index}`}
                    >
                      {action.name}
                    </Label>
                    {!action.waivable && (
                      <span className="text-muted-foreground text-xs">{t("alwaysAsks")}</span>
                    )}
                  </div>
                ))}
              </fieldset>
            ))}
          </section>
        );
      })}
      {shown.length === 0 && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("noMatches")}
        </p>
      )}
    </div>
  );
}
