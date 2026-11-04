"use client";

import { useTranslations } from "next-intl";
import { Checkbox, FormField, Input, Label } from "@/components/ui";
import type { EventSource } from "@/types/triggers";

interface EventOptionsProps {
  source: EventSource;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  canManageConnections?: boolean;
}

/** Source-specific options shared by preset creation and the trigger editor. */
export function EventOptions({
  source,
  config,
  onChange,
  canManageConnections = false,
}: EventOptionsProps) {
  const t = useTranslations("portals");
  function text(key: string, label: string, list = false) {
    const value = config[key];
    return (
      <FormField key={key} label={t(label)} htmlFor={`event-option-${key}`}>
        <Input
          id={`event-option-${key}`}
          value={Array.isArray(value) ? value.join(", ") : typeof value === "string" ? value : ""}
          onChange={(event) => {
            const next = { ...config };
            const value = event.target.value;
            if (value.trim())
              next[key] = list
                ? value
                    .split(",")
                    .map((entry) => entry.trim())
                    .filter(Boolean)
                : value;
            else delete next[key];
            onChange(next);
          }}
        />
      </FormField>
    );
  }
  function toggle(key: string, label: string) {
    return (
      <div className="flex items-center gap-2">
        <Checkbox
          id={`event-option-${key}`}
          checked={config[key] === true}
          onCheckedChange={(checked) => onChange({ ...config, [key]: checked === true })}
        />
        <Label htmlFor={`event-option-${key}`}>{t(label)}</Label>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {source === "gmail" && text("label", "mailLabelFilter")}
      {source === "outlook" && text("folder", "mailFolderFilter")}
      {source === "outlook" && canManageConnections && text("mailbox", "sharedMailboxFilter")}
      {(source === "google_drive" || source === "microsoft_files") &&
        toggle("include_own_changes", "includeOwnChanges")}
      {source === "microsoft_files" && text("name_contains", "nameFilterLabel")}
      {source === "github" &&
        config.event === "issue_comment" &&
        text("mention", "mentionFilterLabel")}
      {source === "github" &&
        ["push", "pull_request", "workflow_run"].includes(String(config.event)) &&
        text("branches", "branchesFilterLabel", true)}
      {(source === "google_calendar" || source === "outlook_calendar") && (
        <>
          <FormField label={t("minutesBeforeLabel")} htmlFor="event-option-minutes">
            <Input
              id="event-option-minutes"
              type="number"
              min={5}
              max={120}
              value={typeof config.minutes_before === "number" ? config.minutes_before : 15}
              onChange={(event) =>
                onChange({ ...config, minutes_before: Number(event.target.value) })
              }
            />
          </FormField>
          {toggle("external_only", "externalOnlyLabel")}
        </>
      )}
    </div>
  );
}

/** Keep incomplete calendar leads in the form until they satisfy the API contract. */
export function eventOptionsValid(config: Record<string, unknown>): boolean {
  const lead = config.minutes_before;
  return (
    lead === undefined ||
    (typeof lead === "number" && Number.isInteger(lead) && lead >= 5 && lead <= 120)
  );
}
