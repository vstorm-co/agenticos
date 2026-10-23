"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SectionCard } from "@/components/settings/settings-section";
import { WorkingHoursField } from "@/components/settings/working-hours-field";
import { Button, FormField, Input } from "@/components/ui";
import { Textarea } from "@/components/ui/textarea";
import { useChanged } from "@/hooks/use-changed";
import { useSaveAgentContext } from "@/hooks/use-account-profile";
import { getErrorMessage } from "@/lib/api-error";
import type { User } from "@/types";
import type { WorkingHours } from "@/types/auth";

const ZONES = Intl.supportedValuesOf("timeZone");

/**
 * What every agent is told about the person, written once (#2301): their role,
 * what they work on, and the time zone "every Monday at 9" is read in. Each
 * agent reads it at the start of every run, so nobody repeats it per chat.
 */
export function AgentContextSettings({ user }: { user: User }) {
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
    setSaving(true);
    try {
      await save({
        job_title: role.trim() || null,
        about: about.trim() || null,
        time_zone: zone || null,
        working_hours: hours,
      });
      toast.success(t("saved"));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SectionCard
      title={t("title")}
      description={t("description")}
      action={
        <Button onClick={submit} disabled={saving} size="sm">
          {t("save")}
        </Button>
      }
    >
      <div className="space-y-4">
        <FormField label={t("role")} htmlFor="agent-context-role">
          <Input
            id="agent-context-role"
            value={role}
            maxLength={120}
            placeholder={t("rolePlaceholder")}
            onChange={(event) => setRole(event.target.value)}
          />
        </FormField>
        <FormField label={t("about")} htmlFor="agent-context-about">
          <Textarea
            id="agent-context-about"
            value={about}
            maxLength={500}
            rows={3}
            placeholder={t("aboutPlaceholder")}
            onChange={(event) => setAbout(event.target.value)}
          />
        </FormField>
        <FormField label={t("timeZone")} htmlFor="agent-context-zone">
          <Input
            id="agent-context-zone"
            list="agent-context-zones"
            value={zone}
            onChange={(event) => setZone(event.target.value)}
          />
          <datalist id="agent-context-zones">
            {ZONES.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </FormField>
        <FormField
          label={t("workingHours")}
          htmlFor="agent-context-hours"
          description={t("workingHoursHint")}
        >
          <WorkingHoursField value={hours} onChange={setHours} />
        </FormField>
      </div>
    </SectionCard>
  );
}
