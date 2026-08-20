"use client";

import { useMemo, useState } from "react";
import { ChevronDown, Cpu, Settings2, Sliders } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { ChatModelPicker } from "./chat-model-picker";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { useModelProviders } from "@/hooks";
import { useConversationStore } from "@/stores";
import type { PublishedModel } from "@/types/agents";
import { cn } from "@/lib/utils";

type ThinkingEffort = "off" | "low" | "medium" | "high";
type Tab = "model" | "settings";

/** The four efforts, in order. Their words live in the catalog under `effort<Level>`. */
const EFFORT_OPTIONS: { value: ThinkingEffort; key: string }[] = [
  { value: "off", key: "Off" },
  { value: "low", key: "Low" },
  { value: "medium", key: "Medium" },
  { value: "high", key: "High" },
];

interface ChatControlsProps {
  /** The model profile this conversation runs on, or null for the agent's own. */
  onModelProfileChange?: (profileId: string | null) => void;
  /** The selected agent's published model, shown as current when there is no override. */
  agentModel?: PublishedModel | null;
  onTemperatureChange?: (value: number | null) => void;
  onThinkingEffortChange?: (value: "low" | "medium" | "high" | null) => void;
}

/**
 * What this conversation overrides, for the turns it sends.
 *
 * Two things and no more. Knowledge bases and MCP servers used to be here as
 * well, and they were at the wrong altitude: what an agent may search and which
 * tools it may reach are part of what the agent *is*, decided once by whoever
 * published it and frozen into the version that runs. Choosing them per chat
 * meant the same published agent answered differently depending on who was
 * typing, with nothing in its history saying so. They belong to the Builder,
 * and that is where they now are.
 *
 * What survives is what a person genuinely decides per conversation: which of
 * the organization's models to spend, and how hard it should think. Both are
 * recorded on the run, so an override stays attributable.
 *
 * The model is chosen the way the Builder chooses one - provider first, then
 * the model - and what runs is still one of the vault's model profiles: a
 * choice that matches an existing profile reuses it, a new one is created on
 * the provider's vault key. An organization that rotates a key changes what
 * this picker can offer, because it is the same set of rows.
 */
export function ChatControls({
  onModelProfileChange,
  agentModel = null,
  onTemperatureChange,
  onThinkingEffortChange,
}: ChatControlsProps) {
  const t = useTranslations("chat.controls");
  const [tab, setTab] = useState<Tab>("model");
  const currentConversationId = useConversationStore((state) => state.currentConversationId);
  const { profiles } = useModelProviders();

  const [profileId, setProfileId] = useState<string | null>(null);
  const [temperature, setTemperature] = useState<number | null>(null);
  const [effort, setEffort] = useState<ThinkingEffort>("off");

  const settingsOverridden = temperature !== null || effort !== "off";
  const selectedProfile = profiles.find((profile) => profile.id === profileId) ?? null;

  const triggerSummary = useMemo(() => {
    const parts: string[] = [];
    if (selectedProfile) parts.push(selectedProfile.label);
    if (settingsOverridden) parts.push(t("custom"));
    return parts.length ? parts.join(" · ") : t("controls");
  }, [selectedProfile, settingsOverridden]);

  const hasOverrides = profileId !== null || settingsOverridden;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("label")}
          // The /settings slash command opens this popover by clicking the
          // trigger through this attribute - see ChatContainer's slashContext.
          data-chat-settings-trigger
          className={cn(
            "border-foreground/10 bg-card hover:border-foreground/25 hover:bg-foreground/[0.04] inline-flex items-center gap-1.5 rounded-full border py-1 pr-2 pl-2.5 font-mono text-[11px] tracking-wider uppercase transition-colors",
            hasOverrides ? "text-foreground" : "text-foreground/65",
          )}
        >
          <Sliders className="h-3 w-3" />
          <span className="max-w-[200px] truncate">{triggerSummary}</span>
          {hasOverrides && (
            <span aria-hidden className="bg-foreground inline-block h-1 w-1 rounded-full" />
          )}
          <ChevronDown className="text-foreground/45 h-3 w-3" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        sideOffset={8}
        className="border-border bg-popover relative w-[380px] overflow-hidden rounded-2xl border p-0 shadow-md"
      >
        <div className="border-foreground/10 flex flex-wrap items-center gap-1 border-b p-2">
          {onModelProfileChange && (
            <TabButton
              icon={Cpu}
              label={t("model")}
              active={tab === "model"}
              onClick={() => setTab("model")}
            />
          )}
          {onTemperatureChange && onThinkingEffortChange && (
            <TabButton
              icon={Settings2}
              label={t("settings")}
              active={tab === "settings"}
              onClick={() => setTab("settings")}
            />
          )}
        </div>

        <div className="max-h-[420px] scrollbar-thin overflow-y-auto p-4">
          {tab === "model" && (
            <div>
              {/* One line, because this is a popover over a text box, not a
                  settings page. What it costs to say the rest here is the four
                  lines of prose that pushed the models themselves below the
                  fold on a laptop.

                  It says what the panel is rather than what the reader may do
                  with it: the picker below checks `connections:manage` and
                  replaces itself with a refusal for a caller without it (#419),
                  and "Run this conversation on a different model" sitting above
                  that refusal promised a control that had gone. */}
              <p className="text-foreground/55 mb-3 text-xs leading-relaxed">
                {t("whichModelRunsHere")}
              </p>
              <ChatModelPicker
                value={profileId}
                agentModel={agentModel}
                onChange={(next) => {
                  setProfileId(next);
                  onModelProfileChange?.(next);
                }}
                // "No override" is not "the organization default": an agent
                // names its own model, and leaving that alone is the default
                // here - so there is no row for one.
              />
              {profileId !== null && (
                <button
                  type="button"
                  onClick={() => {
                    setProfileId(null);
                    onModelProfileChange?.(null);
                  }}
                  className="text-foreground/55 hover:text-foreground mt-3 text-[11px] underline-offset-2 hover:underline"
                >
                  {t("backAgentAposS")}
                </button>
              )}
            </div>
          )}
          {tab === "settings" && (
            <SettingsPanel
              temperature={temperature}
              effort={effort}
              onTemperatureChange={(value) => {
                setTemperature(value);
                onTemperatureChange?.(value);
              }}
              onEffortChange={(value) => {
                setEffort(value);
                onThinkingEffortChange?.(value === "off" ? null : value);
              }}
            />
          )}
        </div>

        <div className="border-foreground/10 text-foreground/45 flex items-center justify-between border-t px-4 py-2 font-mono text-[10px] tracking-wider uppercase">
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className="bg-foreground inline-block h-1 w-1 animate-pulse rounded-full"
            />
            {currentConversationId ? t("savedForChat") : t("savesOnSend")}
          </span>
          <span>{t("escToClose")}</span>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function TabButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-full px-2.5 py-1.5 font-mono text-[11px] tracking-wider uppercase transition-colors",
        active
          ? "bg-foreground text-background"
          : "text-foreground/55 hover:bg-foreground/[0.04] hover:text-foreground",
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}

/** Chat settings panel - temperature + thinking effort. */
function SettingsPanel({
  temperature,
  effort,
  onTemperatureChange,
  onEffortChange,
}: {
  temperature: number | null;
  effort: ThinkingEffort;
  onTemperatureChange: (v: number | null) => void;
  onEffortChange: (v: ThinkingEffort) => void;
}) {
  const t = useTranslations("chat.controls");
  return (
    <div className="space-y-6">
      <div className="space-y-2.5">
        <div className="flex items-baseline justify-between">
          <label htmlFor="chat-temp" className="text-foreground text-sm font-semibold">
            {t("temperature")}
          </label>
          <span className="text-foreground font-mono text-xs tabular-nums">
            {temperature === null ? (
              <span className="text-foreground/55">{t("temperatureDefault")}</span>
            ) : (
              temperature.toFixed(2)
            )}
          </span>
        </div>
        <input
          id="chat-temp"
          type="range"
          min={0}
          max={2}
          step={0.05}
          value={temperature ?? 0.7}
          onChange={(e) => onTemperatureChange(parseFloat(e.target.value))}
          className="bg-foreground/15 h-1.5 w-full cursor-pointer appearance-none rounded-full accent-[var(--color-brand)]"
        />
        <div className="text-foreground/45 flex justify-between font-mono text-[10px] tracking-wider uppercase">
          <span>{t("focused")}</span>
          <span>{t("creative")}</span>
        </div>
        {temperature !== null && (
          <button
            type="button"
            onClick={() => onTemperatureChange(null)}
            className="text-foreground/55 hover:text-foreground text-[11px] underline-offset-2 hover:underline"
          >
            {t("resetToServerDefault")}
          </button>
        )}
      </div>

      <div className="space-y-2.5">
        <div className="flex items-baseline justify-between">
          <span className="text-foreground text-sm font-semibold">{t("thinkingEffort")}</span>
          <span className="text-foreground/45 text-[10px]">{t("modelDependent")}</span>
        </div>
        <div className="grid grid-cols-4 gap-1">
          {EFFORT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => onEffortChange(opt.value)}
              className={cn(
                "rounded-lg px-2 py-1.5 font-mono text-[11px] tracking-wider uppercase transition-colors",
                effort === opt.value
                  ? "bg-foreground text-background"
                  : "border-foreground/15 text-foreground/55 hover:text-foreground border",
              )}
            >
              {t(`effort${opt.key}`)}
            </button>
          ))}
        </div>
        <p className="text-foreground/55 text-[11px]">
          {t(`effort${EFFORT_OPTIONS.find((o) => o.value === effort)?.key ?? t("off")}Hint`)}
        </p>
      </div>

      <p className="text-foreground/45 text-[10px] leading-relaxed">
        {t("settingsPersistCurrentChat")}
      </p>
    </div>
  );
}
