"use client";

import { SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgents, useMembers } from "@/hooks";
import type { WidgetOptions } from "@/lib/dashboard/layouts";
import { PERIOD_PRESETS, type PeriodPreset } from "@/lib/dashboard/period";
import { optionSpec, type WidgetId, type WidgetStyle } from "@/lib/dashboard/registry";
import { useOrgStore } from "@/stores";
import { cn } from "@/lib/utils";

/**
 * The sentinel a Radix select uses for "no narrowing". An empty string is not
 * a legal `SelectItem` value, and `undefined` cannot be selected back to.
 */
const ANY = "__any";

/**
 * One card's own settings, edited where the card is arranged.
 *
 * What it offers is the widget's own declaration (`WIDGETS[id].options`), never
 * a fixed list: a card whose data has no window shows no window control, and a
 * card with one presentation shows no style control. A widget declaring nothing
 * gets no button at all - see {@link hasOptions}.
 *
 * Every control's first choice is "follow the page", and choosing it clears the
 * setting rather than storing today's value. That is the difference between a
 * card that tracks the page filter and a card that happens to agree with it
 * this morning.
 */
export function WidgetOptionsMenu({
  widget,
  title,
  options,
  onChange,
}: {
  widget: WidgetId;
  /** The card's title, so the trigger's label names which card it opens. */
  title: string;
  options: WidgetOptions | undefined;
  onChange: (options: WidgetOptions | undefined) => void;
}) {
  const t = useTranslations("dashboard");
  const spec = optionSpec(widget);
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  // Both catalogs are already on the page (the agents card, the members card),
  // so these resolve from cache rather than costing a request per open.
  const { agents } = useAgents();
  const { members } = useMembers(spec.person ? (activeOrgId ?? "") : "");

  /** Merge one setting in, and drop the whole object when nothing is left. */
  const set = (patch: Partial<WidgetOptions>) => {
    const next: WidgetOptions = { ...options, ...patch };
    for (const key of Object.keys(next) as (keyof WidgetOptions)[]) {
      if (next[key] === undefined) delete next[key];
    }
    onChange(Object.keys(next).length > 0 ? next : undefined);
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          data-no-drag
          className={cn(
            "text-muted-foreground hover:text-foreground size-6",
            options && "text-brand hover:text-brand",
          )}
          aria-label={t("edit.optionsFor", { title })}
        >
          <SlidersHorizontal className="size-3.5" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" data-no-drag className="w-72 space-y-4">
        {spec.period ? (
          <Group label={t("options.window")}>
            <Choices
              value={options?.period ?? ANY}
              onSelect={(value) =>
                set({ period: value === ANY ? undefined : (value as PeriodPreset) })
              }
              choices={[
                { value: ANY, label: t("options.followPage") },
                ...PERIOD_PRESETS.map((preset) => ({
                  value: preset,
                  label: t(`period.${preset}`),
                })),
              ]}
            />
          </Group>
        ) : null}

        {spec.styles && spec.styles.length > 1 ? (
          <Group label={t("options.style")}>
            <Choices
              value={options?.style ?? spec.styles[0] ?? ANY}
              onSelect={(value) =>
                set({ style: value === spec.styles?.[0] ? undefined : (value as WidgetStyle) })
              }
              choices={spec.styles.map((style) => ({
                value: style,
                label: t(`styles.${style}`),
              }))}
            />
          </Group>
        ) : null}

        {spec.agent ? (
          <Group label={t("options.agent")}>
            <Picker
              value={options?.agentId ?? ANY}
              placeholder={t("options.allAgents")}
              onSelect={(value) => set({ agentId: value === ANY ? undefined : value })}
              items={[
                { value: ANY, label: t("options.allAgents") },
                ...agents.map((agent) => ({ value: agent.id, label: agent.name })),
              ]}
            />
          </Group>
        ) : null}

        {spec.person ? (
          <Group label={t("options.person")}>
            <Picker
              value={options?.userId ?? ANY}
              placeholder={t("options.everyone")}
              onSelect={(value) => set({ userId: value === ANY ? undefined : value })}
              items={[
                { value: ANY, label: t("options.everyone") },
                ...members.map((member) => ({
                  value: member.user_id,
                  label: member.full_name || member.email,
                })),
              ]}
            />
          </Group>
        ) : null}

        {options ? (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => onChange(undefined)}
          >
            {t("options.reset")}
          </Button>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

/** Whether a widget offers anything to change - the editor hides the button otherwise. */
export function hasOptions(widget: WidgetId): boolean {
  const spec = optionSpec(widget);
  return Boolean(spec.period || spec.agent || spec.person || (spec.styles?.length ?? 0) > 1);
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-muted-foreground text-xs font-medium">{label}</p>
      {children}
    </div>
  );
}

/**
 * A row of small toggles, for the short closed sets - six windows, two styles.
 * A select would hide four of six choices behind a click each.
 */
function Choices({
  value,
  choices,
  onSelect,
}: {
  value: string;
  choices: { value: string; label: string }[];
  onSelect: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {choices.map((choice) => (
        <button
          key={choice.value}
          type="button"
          onClick={() => onSelect(choice.value)}
          aria-pressed={value === choice.value}
          className={cn(
            "rounded-md px-2 py-1 text-xs transition-colors",
            value === choice.value
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground",
          )}
        >
          {choice.label}
        </button>
      ))}
    </div>
  );
}

/** A select, for the open sets - every agent, every colleague. */
function Picker({
  value,
  items,
  placeholder,
  onSelect,
}: {
  value: string;
  items: { value: string; label: string }[];
  placeholder: string;
  onSelect: (value: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onSelect}>
      <SelectTrigger className="h-8 text-xs">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value} className="text-xs">
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
