"use client";

import { useState, type ReactNode } from "react";
import { CalendarClock, MessageCircle, Moon, Radar, Wallet, type LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { SetupIndicator } from "@/components/settings/setup-indicator";
import { proactivitySetupHints } from "@/lib/setup-hints";
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
import { useTenantId } from "@/hooks/use-organizations";
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
 * connections share a per-person background budget managed by `budgets:manage`.
 * Only conversation suggestions require the organization model; monitoring
 * uses its selected agent. The welcome message spends nothing and is the
 * organization's settings.
 */
export function OrgProactivity({ org }: { org: Organization }) {
  const t = useTranslations("teams.proactive");
  const { can } = usePermissions();
  const tenantId = useTenantId();
  const { switchOrg } = useOrganizations();
  const nightly = can(Perm.budgetsManage);
  const welcome = can(Perm.orgSettings);
  if (tenantId !== org.id) {
    return (
      <SettingsSection title={t("title")} description={t("description")}>
        <p className="text-muted-foreground text-sm">{t("switchOrganizationHint")}</p>
        <Button onClick={() => switchOrg(org.id)}>
          {t("switchOrganization", { name: org.name })}
        </Button>
      </SettingsSection>
    );
  }
  if (!nightly && !welcome) return null;
  return (
    <div className="space-y-5">
      <header className="space-y-1.5">
        <h2 className="text-lg font-semibold tracking-tight">{t("title")}</h2>
        <p className="text-muted-foreground max-w-3xl text-sm leading-relaxed">
          {t("description")}
        </p>
      </header>
      {nightly && <NightlyForm key={org.id} org={org} />}
      {welcome && <WelcomeForm org={org} />}
    </div>
  );
}

/** A feature's switch and explanation stay together, even when its settings are hidden. */
function FeaturePanel({
  title,
  status,
  description,
  icon: Icon,
  id,
  checked,
  disabled,
  onChange,
  children,
}: {
  title: string;
  status?: ReactNode;
  description: string;
  icon: LucideIcon;
  id: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
  children?: ReactNode;
}) {
  return (
    <section aria-label={title} className="bg-card overflow-hidden rounded-xl border">
      <header className="flex items-start gap-3 p-4 sm:p-5">
        <span className="bg-muted text-foreground/80 grid size-9 shrink-0 place-items-center rounded-lg">
          <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Label htmlFor={id} className="text-sm font-semibold">
              {title}
            </Label>
            {status}
          </div>
          <p className="text-muted-foreground text-sm leading-relaxed">{description}</p>
        </div>
        <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
      </header>
      {children && <div className="border-t px-4 py-4 sm:px-5">{children}</div>}
    </section>
  );
}

function NightlyForm({ org }: { org: Organization }) {
  const t = useTranslations("teams.proactive");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { setProactivity } = useOrganizations();
  const { profiles, profilesStatus } = useModelProviders();
  const { can } = usePermissions();
  const [form, setForm] = useState(() => stored(org));
  const [pendingCreations, setPendingCreations] = useState(0);
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
    if (form.enabled && form.modelId === null) {
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
      <div className="grid items-stretch gap-4 lg:grid-cols-2">
        <FeaturePanel
          title={t("nightly")}
          status={<SetupIndicator hints={proactivitySetupHints(org)} />}
          description={t("nightlyHint")}
          icon={Moon}
          id="org-proactive-enabled"
          checked={form.enabled}
          disabled={saving}
          onChange={(enabled) => edit({ enabled })}
        />
        <FeaturePanel
          title={t("watches")}
          description={t("watchesHint")}
          icon={Radar}
          id="org-proactive-watches"
          checked={form.watches}
          disabled={saving}
          onChange={(watches) => edit({ watches })}
        />
      </div>
      <p className="text-muted-foreground max-w-4xl text-xs leading-relaxed">
        {t("runAttribution")}
      </p>
      {form.enabled && (
        <div className="bg-card rounded-xl border p-4 sm:p-5">
          <fieldset
            id="org-proactive-model"
            className="min-w-0 space-y-2"
            disabled={saving}
            aria-invalid={!!errors[MODEL_FIELD]}
            aria-describedby={
              errors[MODEL_FIELD] ? "org-proactive-model-error" : "org-proactive-model-hint"
            }
          >
            <legend className="text-sm font-medium" data-tour="org-proactivity-model">
              {t("model")}
            </legend>
            <ModelProfilePicker
              profiles={profiles}
              profilesStatus={profilesStatus}
              value={form.modelId}
              onChange={(modelId) => edit({ modelId })}
              onCreationPendingChange={(pending) =>
                setPendingCreations((count) => count + (pending ? 1 : -1))
              }
              allowAdd={can(Perm.connectionsManage)}
              disabled={saving}
            />
            {errors[MODEL_FIELD] ? (
              <p id="org-proactive-model-error" className="text-destructive text-xs">
                {errors[MODEL_FIELD]}
              </p>
            ) : (
              <p id="org-proactive-model-hint" className="text-muted-foreground text-xs">
                {t("modelHint")}
              </p>
            )}
          </fieldset>
        </div>
      )}
      {(form.enabled || form.watches) && (
        <div className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <SettingsSection title={t("budgetTitle")}>
            <div className="mb-3 flex items-center gap-2 text-sm">
              <Wallet aria-hidden className="text-muted-foreground size-4 shrink-0" />
              <p className="text-muted-foreground leading-relaxed">{t("budgetHint")}</p>
            </div>
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
            {form.watches && (
              <div className="mt-4 border-t pt-4">
                <WatchPolicy minutes={form.watchMinutes} disabled={saving} onChange={edit} />
              </div>
            )}
          </SettingsSection>
          <SettingsSection title={t("deliveryTitle")}>
            <div className="mb-4 flex items-start gap-2 text-sm">
              <CalendarClock aria-hidden className="text-muted-foreground mt-0.5 size-4 shrink-0" />
              <p className="text-muted-foreground leading-relaxed">{t("deliveryHint")}</p>
            </div>
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
                          "min-h-9 min-w-9 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors",
                          on
                            ? "border-foreground/20 bg-accent text-foreground"
                            : "border-border bg-background text-muted-foreground hover:text-foreground",
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
          </SettingsSection>
        </div>
      )}
      {changed && (
        <div className="bg-card sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 shadow-lg">
          <p role="status" className="text-muted-foreground text-sm">
            {t("unsavedChanges")}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              disabled={saving || pendingCreations > 0}
              onClick={() => {
                setForm(saved);
                setErrors({});
              }}
            >
              {t("discardChanges")}
            </Button>
            <Button onClick={save} disabled={saving || pendingCreations > 0} loading={saving}>
              {t("save")}
            </Button>
          </div>
        </div>
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
    <div>
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
    <FeaturePanel
      title={t("welcome")}
      description={t("welcomeHint")}
      icon={MessageCircle}
      id="org-welcome-enabled"
      checked={form.enabled}
      disabled={saving}
      onChange={(enabled) => setForm((current) => ({ ...current, enabled }))}
    >
      {(form.enabled || changed) && (
        <div className="space-y-4">
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
                onChange={(event) =>
                  setForm((current) => ({ ...current, text: event.target.value }))
                }
              />
            </FormField>
          )}
          {changed && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p role="status" className="text-muted-foreground text-sm">
                {t("unsavedChanges")}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  disabled={saving}
                  onClick={() => {
                    setForm(saved);
                    setError(null);
                  }}
                >
                  {t("discardChanges")}
                </Button>
                <Button onClick={save} disabled={saving} loading={saving}>
                  {t("save")}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </FeaturePanel>
  );
}
