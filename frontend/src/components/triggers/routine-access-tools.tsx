"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { ChevronDown, Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import { useBranding } from "@/components/branding/branding-provider";
import { RoutineAccessSetting } from "@/components/triggers/routine-access-setting";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  Input,
  Label,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import {
  mayRunFreely,
  routineToolIdentity as identity,
  type RoutineAccessReview,
  type RoutineDelegateSetting,
  type RoutineToolOption,
  type RoutineToolSettingValue,
} from "@/lib/routine-access-api";

/** What the Set all menu does; see `setAll` in the dialog. */
export type SetAll = "agent" | "ask" | "allow";

/**
 * Which Set all choice the current settings amount to, or `custom` when a tool
 * was set by hand. "As the agent" wins where two choices give the same settings.
 */
export function currentSetAll(
  review: RoutineAccessReview,
  settings: ReadonlyMap<string, RoutineToolSettingValue>,
): SetAll | "custom" {
  const asAgent = (tool: RoutineToolOption) =>
    mayRunFreely(tool, review.can_allow) ? "allow" : "ask";
  const tools = review.tools.map((tool) => ({ tool, value: settings.get(identity(tool)) }));
  if (tools.every(({ tool, value }) => value === asAgent(tool))) return "agent";
  if (tools.every(({ value }) => value === "ask" || value === "off")) return "ask";
  if (tools.every(({ tool, value }) => value === "off" || value === asAgent(tool))) return "allow";
  return "custom";
}

interface Group {
  name: string | null;
  tools: RoutineToolOption[];
}
interface Section {
  name: string;
  groups: Map<string, Group>;
}

const ALL: readonly RoutineToolSettingValue[] = ["allow", "ask", "off"];
const ASKING: readonly RoutineToolSettingValue[] = ["ask", "off"];
const DELEGATE: readonly RoutineDelegateSetting[] = ["allow", "ask"];

/**
 * Every tool the routine's agent gives it, grouped by capability, account and
 * platform group, each with its own Run freely / Ask first / Off.
 */
export function RoutineAccessTools({
  agentId,
  review,
  settings,
  delegates,
  disabled,
  onTool,
  onDelegates,
  onSetAll,
}: {
  agentId: string;
  review: RoutineAccessReview;
  settings: ReadonlyMap<string, RoutineToolSettingValue>;
  delegates: RoutineDelegateSetting;
  disabled: boolean;
  onTool: (tool: RoutineToolOption, value: RoutineToolSettingValue) => void;
  onDelegates: (value: RoutineDelegateSetting) => void;
  onSetAll: (choice: SetAll) => void;
}) {
  const t = useTranslations("triggers.access");
  const agents = useTranslations("agents");
  const { appName } = useBranding();
  const id = useId();
  const [query, setQuery] = useState("");
  const refusal = review.can_allow
    ? null
    : t("allowRefused", { reason: review.allow_blocked_reason ?? "other" });
  const sections = new Map<string, Section>();
  for (const tool of review.tools) {
    const [sectionKey, sectionName, groupKey, groupName] =
      "capability_id" in tool
        ? ["capabilities", t("capabilities"), tool.capability_id, tool.capability_name]
        : "kind" in tool
          ? ["platform", appName, tool.group, agents("platformToolGroup", { group: tool.group })]
          : [
              `account:${tool.connection_id}`,
              t(tool.account_scope === "personal" ? "personalAccount" : "organizationAccount", {
                name: tool.account_name,
              }),
              "",
              null,
            ];
    const section = sections.get(sectionKey) ?? { name: sectionName, groups: new Map() };
    const group = section.groups.get(groupKey) ?? { name: groupName, tools: [] };
    group.tools.push(tool);
    section.groups.set(groupKey, group);
    sections.set(sectionKey, section);
  }
  const needle = query.trim().toLowerCase();
  const shown = [...sections.entries()].flatMap(([sectionKey, section]) => {
    const groups = [...section.groups.entries()]
      .map(([groupKey, group]) => ({
        groupKey,
        name: group.name,
        tools: group.tools.filter((tool) =>
          `${section.name} ${group.name ?? ""} ${tool.name}`.toLowerCase().includes(needle),
        ),
      }))
      .filter((group) => group.tools.length > 0);
    return groups.length ? [{ sectionKey, name: section.name, groups }] : [];
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1 space-y-1">
          <Label htmlFor={`${id}-search`}>{t("search")}</Label>
          <Input
            id={`${id}-search`}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" disabled={disabled || review.tools.length === 0}>
              {t("setAllCurrent", { choice: currentSetAll(review, settings) })}
              <ChevronDown aria-hidden className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuRadioGroup
              value={currentSetAll(review, settings)}
              onValueChange={(value) => {
                if (value === "agent" || value === "ask" || value === "allow") onSetAll(value);
              }}
            >
              <DropdownMenuRadioItem value="agent">{t("setAllAgent")}</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="ask">{t("setAllAsk")}</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="allow">{t("setAllAllow")}</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {review.unlisted_accounts.length > 0 && (
        <p role="note" className="text-muted-foreground text-sm">
          {t("unlisted", { names: review.unlisted_accounts.join(", ") })}{" "}
          <Link
            className="text-foreground underline underline-offset-4"
            href={`${ROUTES.AGENT_DETAIL(agentId)}?highlight=agent-mcp`}
          >
            {t("inspectAgent")}
          </Link>
        </p>
      )}
      {review.tools.length === 0 && <p className="text-muted-foreground text-sm">{t("noTools")}</p>}
      {review.tools.length > 0 && shown.length === 0 && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("noMatches")}
        </p>
      )}
      {shown.map((section, sectionIndex) => (
        <section
          key={section.sectionKey}
          aria-label={section.name}
          className="min-w-0 space-y-2 rounded-lg border p-3"
        >
          <h4 id={`${id}-${sectionIndex}`} className="text-sm font-semibold break-words">
            {section.name}
          </h4>
          {section.groups.map((group, groupIndex) => (
            <div key={group.groupKey} className="min-w-0 space-y-1">
              {group.name !== null && (
                <p
                  id={`${id}-${sectionIndex}-${groupIndex}`}
                  className="text-muted-foreground text-xs font-medium break-words"
                >
                  {group.name}
                </p>
              )}
              {group.tools.map((tool) => (
                <ToolRow
                  key={identity(tool)}
                  tool={tool}
                  // Two accounts can offer the same tool name; this says whose it is.
                  describedBy={[
                    `${id}-${sectionIndex}`,
                    ...(group.name === null ? [] : [`${id}-${sectionIndex}-${groupIndex}`]),
                  ].join(" ")}
                  value={settings.get(identity(tool)) ?? "ask"}
                  refused={mayRunFreely(tool, review.can_allow) ? null : refusal}
                  disabled={disabled}
                  onChange={(value) => onTool(tool, value)}
                />
              ))}
            </div>
          ))}
        </section>
      ))}
      {review.has_delegates && (
        <section
          aria-label={t("delegates")}
          className="flex min-w-0 flex-wrap items-center gap-3 rounded-lg border p-3"
        >
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">{t("delegates")}</p>
            <p id={`${id}-delegates`} className="text-muted-foreground text-xs">
              {t("delegatesHint")}
            </p>
          </div>
          <RoutineAccessSetting
            label={t("delegates")}
            describedBy={`${id}-delegates`}
            value={delegates}
            options={DELEGATE}
            refused={refusal}
            disabled={disabled}
            onChange={onDelegates}
          />
        </section>
      )}
    </div>
  );
}

function ToolRow({
  tool,
  describedBy,
  value,
  refused,
  disabled,
  onChange,
}: {
  tool: RoutineToolOption;
  describedBy: string;
  value: RoutineToolSettingValue;
  refused: string | null;
  disabled: boolean;
  onChange: (value: RoutineToolSettingValue) => void;
}) {
  const t = useTranslations("triggers.access");
  const locked = tool.agent === "ask";
  return (
    <div className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        <span className="text-sm break-all">{tool.name}</span>
        <Badge variant="outline">{t(tool.effect ? "changes" : "reads")}</Badge>
        {tool.setting === null && <Badge variant="secondary">{t("new")}</Badge>}
        {locked && (
          <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
            <Lock aria-hidden className="size-3" />
            {t("locked")}
          </span>
        )}
      </div>
      <RoutineAccessSetting
        label={tool.name}
        describedBy={describedBy}
        value={value}
        options={locked ? ASKING : ALL}
        // A tool the agent asks before never offers Run freely, so nothing to explain.
        refused={locked ? null : refused}
        disabled={disabled}
        onChange={onChange}
      />
    </div>
  );
}
