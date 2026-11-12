"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SectionCard } from "@/components/settings/settings-section";
import { TimeZonePicker } from "@/components/settings/time-zone-picker";
import { WorkingHoursField } from "@/components/settings/working-hours-field";
import { Button, FormField, Input } from "@/components/ui";
import { Textarea } from "@/components/ui/textarea";
import { useChanged } from "@/hooks/use-changed";
import { useSaveAgentContext } from "@/hooks/use-account-profile";
import { getErrorMessage } from "@/lib/api-error";
import type { User } from "@/types";
import type { WorkingHours } from "@/types/auth";

/**
 * What every agent is told about the person, written once (#2301): their role,
 * what they work on, and the time zone "every Monday at 9" is read in. Each
 * agent reads it at the start of every run, so nobody repeats it per chat.
 */
export function AgentContextSettings({
  user,
  beforeSave,
  onSaved,
  saveLabel,
  secondaryAction,
  disabled = false,
  onSavingChange,
}: {
  user: User;
  beforeSave?: () => Promise<boolean>;
  onSaved?: () => void;
  saveLabel?: string;
  secondaryAction?: ReactNode;
  disabled?: boolean;
  onSavingChange?: (saving: boolean) => void;
}) {
  const t = useTranslations("pages.settings.agentContext");
  const tErrors = useTranslations("errors");
  const save = useSaveAgentContext();
  const [role, setRole] = useState(user.job_title ?? "");
  const [about, setAbout] = useState(user.about ?? "");
  const [zone, setZone] = useState(user.time_zone ?? "");
  const [hours, setHours] = useState<WorkingHours | null>(user.working_hours ?? null);
  const [saving, setSaving] = useState(false);

  const stored = JSON.stringify(user.working_hours ?? null);
  if (useChanged(`${user.id}|${user.job_title}|${user.about}|${user.time_zone}|${stored}`)) {
    setRole(user.job_title ?? "");
    setAbout(user.about ?? "");
    setZone(user.time_zone ?? "");
    setHours(user.working_hours ?? null);
  }

  const submit = async () => {
    if (saving || disabled) return;
    setSaving(true);
    onSavingChange?.(true);
    try {
      if (beforeSave && !(await beforeSave())) return;
      await save({
        job_title: role.trim() || null,
        about: about.trim() || null,
        time_zone: zone || null,
        working_hours: hours,
      });
      toast.success(t("saved"));
      onSaved?.();
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    } finally {
      setSaving(false);
      onSavingChange?.(false);
    }
  };

  return (
    <SectionCard title={t("title")} description={t("description")}>
      <form
        aria-label={t("title")}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <fieldset disabled={saving || disabled} className="grid min-w-0 gap-5 sm:grid-cols-2">
          <legend className="sr-only">{t("title")}</legend>
          <FormField label={t("role")} htmlFor="agent-context-role">
            <Input
              id="agent-context-role"
              data-guidance={(!!onSaved && !role.trim()) || undefined}
              value={role}
              maxLength={120}
              placeholder={t("rolePlaceholder")}
              onChange={(event) => setRole(event.target.value)}
            />
          </FormField>
          <FormField label={t("timeZone")} htmlFor="agent-context-zone">
            <TimeZonePicker
              id="agent-context-zone"
              data-guidance={(!!onSaved && !!role.trim() && !zone) || undefined}
              value={zone}
              onChange={setZone}
              disabled={saving || disabled}
            />
          </FormField>
          <FormField className="sm:col-span-2" label={t("about")} htmlFor="agent-context-about">
            <Textarea
              id="agent-context-about"
              value={about}
              maxLength={500}
              rows={3}
              placeholder={t("aboutPlaceholder")}
              onChange={(event) => setAbout(event.target.value)}
            />
          </FormField>
          <FormField
            className="sm:col-span-2"
            label={t("workingHours")}
            htmlFor="agent-context-hours"
            description={t("workingHoursHint")}
          >
            <WorkingHoursField value={hours} onChange={setHours} disabled={saving || disabled} />
          </FormField>
          <div
            data-profile-actions
            className="flex flex-wrap items-center justify-end gap-3 border-t pt-4 sm:col-span-2"
          >
            <Button
              type="submit"
              loading={saving}
              disabled={saving || disabled}
              className="w-full sm:w-auto"
            >
              {saveLabel ?? t("save")}
            </Button>
            {secondaryAction}
          </div>
        </fieldset>
      </form>
    </SectionCard>
  );
}
