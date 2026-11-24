"use client";

import { Check } from "lucide-react";
import { useId } from "react";
import { useTranslations } from "next-intl";
import { hasKey, runsAgents, usableForAgents } from "@/lib/model-profiles";
import type { ModelProfile } from "@/types/providers";

export function ChatModelOptions({
  profiles,
  value,
  accountName,
  onChange,
}: {
  profiles: ModelProfile[];
  value: string | null;
  accountName: (profile: ModelProfile) => string;
  onChange: (profileId: string) => void;
}) {
  const t = useTranslations("chat.modelSelector");
  const descriptionId = useId();
  const tabStop =
    profiles.find((profile) => profile.id === value && usableForAgents(profile))?.id ??
    profiles.find(usableForAgents)?.id;
  return (
    <div
      role="radiogroup"
      tabIndex={-1}
      aria-label={t("savedModels")}
      className="max-h-64 space-y-1 overflow-y-auto"
      onKeyDown={(event) => {
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
        const buttons = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"),
        );
        if (buttons.length === 0) return;
        event.preventDefault();
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? buttons.length - 1
              : current < 0
                ? event.key === "ArrowDown"
                  ? 0
                  : buttons.length - 1
                : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) %
                  buttons.length;
        buttons[next]?.focus();
      }}
    >
      {profiles.map((profile) => (
        <button
          key={profile.id}
          type="button"
          role="radio"
          aria-checked={profile.id === value}
          aria-label={profile.label}
          aria-describedby={
            !usableForAgents(profile) ? `${descriptionId}-${profile.id}` : undefined
          }
          tabIndex={profile.id === tabStop ? 0 : -1}
          disabled={!usableForAgents(profile)}
          onClick={() => onChange(profile.id)}
          className="hover:bg-accent disabled:text-muted-foreground flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium">{profile.label}</span>
            <span className="text-muted-foreground block truncate text-[11px]">
              {profile.model}
            </span>
            <span className="text-muted-foreground block truncate text-[11px]">
              {accountName(profile)}
            </span>
            {profile.base_url && (
              <span className="text-muted-foreground block truncate text-[10px]">
                {profile.base_url}
              </span>
            )}
            <span id={`${descriptionId}-${profile.id}`}>
              {!hasKey(profile) && (
                <span className="text-destructive block text-[11px]">{t("missingKey")}</span>
              )}
              {!runsAgents(profile) && (
                <span className="text-destructive block text-[11px]">{t("notChatModel")}</span>
              )}
            </span>
          </span>
          {profile.id === value && <Check aria-hidden className="size-4 shrink-0" />}
        </button>
      ))}
    </div>
  );
}
