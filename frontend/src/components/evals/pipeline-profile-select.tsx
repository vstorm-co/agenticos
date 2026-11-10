"use client";

import { useId, useState } from "react";
import { Command } from "cmdk";
import { Check, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { ProviderIcon } from "@/components/vault/provider-icon";
import { Badge, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { COMMAND_ITEM_FOCUS, FORM_CONTROL } from "@/components/ui/control-styles";
import { hasKey, modelDetail, runsAgents, usableForAgents } from "@/lib/model-profiles";
import { cn } from "@/lib/utils";
import type { ModelProfile } from "@/types/providers";

/** Saved pipeline models stay compact; search matches the label, provider and model. */
export function PipelineProfileSelect({
  profiles,
  value,
  onChange,
  disabled,
}: {
  profiles: ModelProfile[];
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");
  const [open, setOpen] = useState(false);
  const listId = useId();
  const selected = profiles.find((profile) => profile.id === value);
  const offered = profiles.filter((profile) => usableForAgents(profile) || profile.id === value);
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{t("model2")}</p>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            role="combobox"
            aria-label={t("model2")}
            aria-controls={listId}
            aria-expanded={open}
            disabled={disabled}
            className={cn(
              FORM_CONTROL,
              "flex min-h-11 w-full items-center gap-3 px-3 py-2 text-left text-sm",
            )}
          >
            {selected && <ProviderIcon provider={selected.provider} />}
            <span className={cn("min-w-0 flex-1 truncate", !selected && "text-muted-foreground")}>
              {selected?.label ?? t("pipelineModelPlaceholder")}
            </span>
            <ChevronsUpDown className="text-muted-foreground size-4 shrink-0" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-[var(--radix-popover-trigger-width)] overflow-hidden p-0"
        >
          <Command>
            <Command.Input
              aria-label={t("searchModels")}
              placeholder={t("searchModels")}
              className="placeholder:text-muted-foreground h-11 w-full border-b bg-transparent px-3 text-sm outline-none"
            />
            <Command.List id={listId} className="max-h-64 overflow-y-auto overscroll-contain p-1.5">
              <Command.Empty className="text-muted-foreground px-3 py-5 text-center text-sm">
                {t("pipelineNoMatches")}
              </Command.Empty>
              {offered.map((profile) => (
                <Command.Item
                  key={profile.id}
                  value={profile.id}
                  keywords={[profile.label, profile.provider, profile.model]}
                  disabled={!usableForAgents(profile)}
                  onSelect={() => {
                    onChange(profile.id);
                    setOpen(false);
                  }}
                  className={cn(
                    COMMAND_ITEM_FOCUS,
                    "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-sm data-[disabled=true]:opacity-50",
                  )}
                >
                  <ProviderIcon provider={profile.provider} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{profile.label}</span>
                    {modelDetail(profile) && (
                      <span className="text-muted-foreground block truncate text-xs">
                        {modelDetail(profile)}
                      </span>
                    )}
                  </span>
                  {!hasKey(profile) && <Badge variant="destructive">{t("noKey")}</Badge>}
                  {!runsAgents(profile) && (
                    <Badge variant="destructive">{t("notAChatModel")}</Badge>
                  )}
                  {profile.id === value && <Check className="size-4 shrink-0" aria-hidden />}
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </PopoverContent>
      </Popover>
      {selected && !runsAgents(selected) && (
        <p role="alert" className="text-destructive-ink text-xs">
          {t("notAChatModelHint", { model: selected.model })}
        </p>
      )}
      {selected && runsAgents(selected) && !hasKey(selected) && (
        <p role="alert" className="text-destructive-ink text-xs">
          {t("modelHasNoKeyHint")}
        </p>
      )}
    </div>
  );
}
