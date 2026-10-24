"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { SettingsSection } from "@/components/settings/settings-section";
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useModelProviders, useOrganizations, usePermissions } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { submitFailure } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { WATCH_INTERVALS, cadenceLabel } from "@/lib/watch-cadence";
import type { Organization, ProactiveTiming } from "@/types";
import { Perm } from "@/types/permissions";

/** The fields the server names in a refusal, so a message lands under its input. */
const MODEL_FIELD = "proactive_model_profile_id";
const LIMIT_FIELD = "proactive_limit_usd";
const TEXT_FIELD = "welcome_dm_text";

/** ISO weekdays, Monday first. 2024-01-01 was a Monday. */
const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;
const MONDAY = Date.UTC(2024, 0, 1);
const DAY_MS = 86_400_000;
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

interface Proactivity {
  enabled: boolean;
  modelId: string | null;
  limit: string;
  days: number[];
  hour: number;
  timing: ProactiveTiming;
  watches: boolean;
  watchMinutes: number;
}

/** What the organization has saved, as the form edits it; "1.000000" reads as "1". */
function stored(org: Organization): Proactivity {
  return {
    enabled: org.proactive_enabled ?? false,
    modelId: org.proactive_model_profile_id ?? null,
    limit: String(Number(org.proactive_limit_usd ?? "1")),
    days: org.proactive_days ?? [1, 2, 3, 4, 5],
    hour: org.proactive_hour ?? 5,
    timing: org.proactive_timing ?? "fixed",
    watches: org.proactive_watches_enabled ?? false,
    watchMinutes: org.proactive_watch_min_minutes ?? 60,
  };
}

/**
 * What the platform does for people on its own initiative (#2301), and whether
 * it does it at all: off until an organization turns it on.
 *
 * Two settings with two owners. The nightly look and the watches over people's
 * connections spend money nobody asked for in the moment, so they are
 * `budgets:manage`'s, on one model chosen rather than defaulted and one limit per
 * person. The welcome message in the chat apps spends nothing and is the
 * organization's settings.
 */
export function OrgProactivity({ org }: { org: Organization }) {
  const t = useTranslations("teams.proactive");
  const { can } = usePermissions();
  const nightly = can(Perm.budgetsManage);
  const welcome = can(Perm.orgSettings);
  if (!nightly && !welcome) return null;
  return (
    <SettingsSection title={t("title")} description={t("description")}>
      <div className="divide-foreground/10 space-y-6 divide-y [&>*:not(:first-child)]:pt-6">
        {nightly && <NightlyForm org={org} />}
        {welcome && <WelcomeForm org={org} />}
      </div>
    </SettingsSection>
  );
}

function NightlyForm({ org }: { org: Organization }) {
  const t = useTranslations("teams.proactive");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { setProactivity } = useOrganizations();
  const { profiles } = useModelProviders();
  const [form, setForm] = useState(() => stored(org));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const saved = stored(org);
  if (useChanged(JSON.stringify(saved))) setForm(saved);
  const changed = JSON.stringify(form) !== JSON.stringify(saved);
  const dayName = new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" });
  const edit = (next: Partial<Proactivity>) => {
    setForm((current) => ({ ...current, ...next }));
    setErrors({});
  };

  const save = async () => {
    const limit = Number(form.limit.trim());
    if (form.limit.trim() === "" || !Number.isFinite(limit) || limit < 0) {
      setErrors({ [LIMIT_FIELD]: t("invalid") });
      return;
    }
    if ((form.enabled || form.watches) && form.modelId === null) {
      setErrors({ [MODEL_FIELD]: t("modelRequired") });
      return;
    }
    setSaving(true);
    try {
      await setProactivity(org.id, {
        proactive_enabled: form.enabled,
        proactive_model_profile_id: form.modelId,
        proactive_limit_usd: limit,
        proactive_days: form.days,
        proactive_hour: form.hour,
        proactive_timing: form.timing,
        proactive_watches_enabled: form.watches,
        proactive_watch_min_minutes: form.watchMinutes,
      });
      toast.success(form.enabled || form.watches ? t("saved") : t("off"));
    } catch (failure) {
      const problem = submitFailure(failure, { fields: [MODEL_FIELD, LIMIT_FIELD] }, tErrors);
      setErrors(problem.fields);
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <Label htmlFor="org-proactive-enabled">{t("nightly")}</Label>
          <p className="text-muted-foreground text-xs leading-relaxed">{t("nightlyHint")}</p>
        </div>
        <Switch
          id="org-proactive-enabled"
          checked={form.enabled}
          disabled={saving}
          onCheckedChange={(enabled) => edit({ enabled })}
        />
      </div>
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <Label htmlFor="org-proactive-watches">{t("watches")}</Label>
          <p className="text-muted-foreground text-xs leading-relaxed">{t("watchesHint")}</p>
        </div>
        <Switch
          id="org-proactive-watches"
          checked={form.watches}
          disabled={saving}
          onCheckedChange={(watches) => edit({ watches })}
        />
      </div>
      {(form.enabled || form.watches) && (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            label={t("model")}
            htmlFor="org-proactive-model"
            description={t("modelHint")}
            error={errors[MODEL_FIELD] ?? null}
          >
            <Select
              value={form.modelId ?? ""}
              onValueChange={(modelId) => edit({ modelId })}
              disabled={saving}
            >
              <SelectTrigger id="org-proactive-model">
                <SelectValue placeholder={t("modelPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {profiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField
            label={t("label")}
            htmlFor="org-proactive-limit"
            error={errors[LIMIT_FIELD] ?? null}
          >
            <Input
              id="org-proactive-limit"
              type="number"
              min="0"
              step="0.5"
              value={form.limit}
              disabled={saving}
              onChange={(event) => edit({ limit: event.target.value })}
            />
          </FormField>
        </div>
      )}
      {form.enabled && (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t("days")} htmlFor="org-proactive-days" className="sm:col-span-2">
            <div
              id="org-proactive-days"
              role="group"
              aria-label={t("days")}
              className="flex flex-wrap gap-1.5"
            >
              {WEEKDAYS.map((day) => {
                const on = form.days.includes(day);
                return (
                  <button
                    key={day}
                    type="button"
                    aria-pressed={on}
                    disabled={saving || (on && form.days.length === 1)}
                    onClick={() =>
                      edit({
                        days: on
                          ? form.days.filter((other) => other !== day)
                          : [...form.days, day].sort((a, b) => a - b),
                      })
                    }
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
                      on
                        ? "bg-foreground text-background border-foreground"
                        : "border-input text-foreground hover:border-foreground/40",
                    )}
                  >
                    {dayName.format(MONDAY + (day - 1) * DAY_MS)}
                  </button>
                );
              })}
            </div>
          </FormField>
          <FormField label={t("timing")} htmlFor="org-proactive-timing">
            <Select
              value={form.timing}
              onValueChange={(timing) => edit({ timing: timing as ProactiveTiming })}
              disabled={saving}
            >
              <SelectTrigger id="org-proactive-timing">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fixed">{t("timingFixed")}</SelectItem>
                <SelectItem value="before_work">{t("timingBeforeWork")}</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField
            label={t("hour")}
            htmlFor="org-proactive-hour"
            description={form.timing === "fixed" ? t("hourHint") : t("hourFallbackHint")}
          >
            <Select
              value={String(form.hour)}
              onValueChange={(hour) => edit({ hour: Number(hour) })}
              disabled={saving}
            >
              <SelectTrigger id="org-proactive-hour">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HOURS.map((hour) => (
                  <SelectItem key={hour} value={String(hour)}>
                    {`${String(hour).padStart(2, "0")}:00`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
      )}
      {form.watches && (
        <WatchPolicy minutes={form.watchMinutes} disabled={saving} onChange={edit} />
      )}
      {changed && (
        <Button onClick={save} disabled={saving}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : t("save")}
        </Button>
      )}
    </div>
  );
}

/** How often a watch may run at most here; any server a person connected may be watched. */
function WatchPolicy({
  minutes,
  disabled,
  onChange,
}: {
  minutes: number;
  disabled: boolean;
  onChange: (next: Partial<Proactivity>) => void;
}) {
  const t = useTranslations("teams.proactive");
  const tCadence = useTranslations("watches.cadence");
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField
        label={t("watchMinutes")}
        htmlFor="org-watch-minutes"
        description={t("watchMinutesHint")}
      >
        <Select
          value={String(minutes)}
          onValueChange={(value) => onChange({ watchMinutes: Number(value) })}
          disabled={disabled}
        >
          <SelectTrigger id="org-watch-minutes">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {WATCH_INTERVALS.map((each) => (
              <SelectItem key={each} value={String(each)}>
                {cadenceLabel(each, tCadence)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
    </div>
  );
}

function WelcomeForm({ org }: { org: Organization }) {
  const t = useTranslations("teams.proactive");
  const tErrors = useTranslations("errors");
  const { setWelcomeDm } = useOrganizations();
  const saved = { enabled: org.welcome_dm_enabled ?? false, text: org.welcome_dm_text ?? "" };
  const [form, setForm] = useState(saved);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  if (useChanged(JSON.stringify(saved))) setForm(saved);
  const changed = form.enabled !== saved.enabled || form.text.trim() !== saved.text;

  const save = async () => {
    setSaving(true);
    try {
      await setWelcomeDm(org.id, {
        welcome_dm_enabled: form.enabled,
        welcome_dm_text: form.text.trim() || null,
      });
      setError(null);
      toast.success(t("welcomeSaved"));
    } catch (failure) {
      const problem = submitFailure(failure, { fields: [TEXT_FIELD] }, tErrors);
      setError(problem.fields[TEXT_FIELD] ?? null);
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <Label htmlFor="org-welcome-enabled">{t("welcome")}</Label>
          <p className="text-muted-foreground text-xs leading-relaxed">{t("welcomeHint")}</p>
        </div>
        <Switch
          id="org-welcome-enabled"
          checked={form.enabled}
          disabled={saving}
          onCheckedChange={(enabled) => setForm((current) => ({ ...current, enabled }))}
        />
      </div>
      {form.enabled && (
        <FormField
          label={t("welcomeText")}
          htmlFor="org-welcome-text"
          description={t("welcomeTextHint")}
          error={error}
        >
          <Textarea
            id="org-welcome-text"
            rows={3}
            maxLength={1000}
            value={form.text}
            disabled={saving}
            placeholder={t("welcomeTextPlaceholder")}
            onChange={(event) => setForm((current) => ({ ...current, text: event.target.value }))}
          />
        </FormField>
      )}
      {changed && (
        <Button onClick={save} disabled={saving}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : t("save")}
        </Button>
      )}
    </div>
  );
}
