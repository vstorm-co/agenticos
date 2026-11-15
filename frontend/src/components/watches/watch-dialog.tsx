"use client";

import { RoutineOptions } from "@/components/triggers/routine-options";

import { FailurePolicyField } from "@/components/triggers/failure-policy-field";
import { NotificationChannelsField } from "@/components/triggers/notification-channels-field";
import type { RoutineNotificationChannel, WatchReportMode } from "@/types/routines";
import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Dialog,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
  MarkdownEditor,
  WizardNav,
} from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { endInput, endInstant, EndsAtField } from "@/components/triggers/ends-at-field";
import { useAgentEnvironments, useMcpConnections, useOrganizations } from "@/hooks";
import { useWatchPresets, useWatches } from "@/hooks/use-watches";
import { submitFailure } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { RoutineDialogFrame } from "@/components/triggers/routine-dialog-frame";
import { cn } from "@/lib/utils";
import { allowedIntervals, cadenceLabel } from "@/lib/watch-cadence";
import type { Watch } from "@/lib/watches-api";
import { WatchAccount, useAccountName } from "./watch-account";
import { WatchAgentFields, WatchExecutionFields } from "./watch-agent-fields";

const CUSTOM = "custom";
const FIELDS = [
  "agent_id",
  "environment_id",
  "pinned_version_id",
  "ends_at",
  "connection_id",
  "interval_minutes",
  "preset_key",
  "title",
  "instructions",
];

interface Draft {
  agentId: string;
  environmentId: string | null;
  pinnedVersionId: string | null;
  connectionId: string;
  presetKey: string;
  title: string;
  instructions: string;
  urgent: boolean;
  interval: number;
  exclusions: string;
}

function startFrom(
  watch: Watch | undefined,
  connectionId: string | undefined,
  agentId: string | undefined,
): Draft {
  return {
    agentId: watch?.agent_id ?? agentId ?? "",
    environmentId: watch?.environment_id ?? null,
    pinnedVersionId: watch?.pinned_version_id ?? null,
    connectionId: watch?.connection_id ?? connectionId ?? "",
    presetKey: watch?.preset_key ?? CUSTOM,
    title: watch?.title ?? "",
    instructions: watch?.instructions ?? "",
    urgent: watch?.urgent ?? false,
    interval: watch?.interval_minutes ?? 60,
    exclusions: (watch?.exclusions ?? []).join("\n"),
  };
}

/**
 * Set up or change one watch (#2301): which of the person's own connections, a
 * ready-made thing to look for or their own words, how often, and whether the
 * urgent ones are sent at once. A preset's words are the console's, in the
 * person's language, and stay editable.
 */
export function WatchDialog({
  open,
  onOpenChange,
  watch,
  connectionId,
  agentId,
  initialTask,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  watch?: Watch;
  connectionId?: string;
  agentId?: string;
  initialTask?: { title: string; instructions: string };
}) {
  const t = useTranslations("watches");
  const tt = useTranslations("triggers");
  const [step, setStep] = useState<"configure" | "message" | "schedule">("configure");
  const tCadence = useTranslations("watches.cadence");
  const tErrors = useTranslations("errors");
  const { connections } = useMcpConnections();
  const presets = useWatchPresets();
  const { activeOrg } = useOrganizations();
  const { create, update } = useWatches();
  const accountName = useAccountName();
  const router = useRouter();
  const onRoutines = usePathname().endsWith(ROUTES.ROUTINES);
  const [draft, setDraft] = useState(() => ({
    ...startFrom(watch, connectionId, agentId),
    ...(!watch && initialTask ? initialTask : {}),
    interval: watch?.interval_minutes ?? Math.max(60, activeOrg?.proactive_watch_min_minutes ?? 15),
  }));
  const [endsAt, setEndsAt] = useState(() => endInput(watch?.ends_at));
  const [endTouched, setEndTouched] = useState(false);
  const [invalidEnd, setInvalidEnd] = useState(false);
  const [versionValid, setVersionValid] = useState(true);
  const [maxFailures, setMaxFailures] = useState<number | null>(
    watch?.max_failures === undefined ? 3 : watch.max_failures,
  );
  const [notificationChannels, setNotificationChannels] = useState<
    RoutineNotificationChannel[] | null
  >(watch?.notification_channels ?? null);
  const [reportMode, setReportMode] = useState<WatchReportMode>(watch?.report_mode ?? "changes");
  const [reviewSources, setReviewSources] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const { error: environmentsError } = useAgentEnvironments(draft.agentId || null);

  const connection = connections.find((each) => each.id === draft.connectionId);
  const offered = presets.filter((preset) => preset.server === connection?.catalog_key);
  const floor = activeOrg?.proactive_watch_min_minutes ?? 15;
  const intervals = [...new Set([...allowedIntervals(floor), draft.interval])]
    .filter((minutes) => minutes >= floor)
    .sort((left, right) => left - right);
  const edit = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }));
    setErrors({});
  };
  const pick = (presetKey: string) => {
    const preset = offered.find((each) => each.key === presetKey);
    edit(
      preset
        ? {
            presetKey,
            title: t(`presets.${preset.key}.title`),
            instructions: t(`presets.${preset.key}.instructions`),
            urgent: preset.urgent,
            interval: Math.max(preset.interval_minutes, floor),
          }
        : { presetKey },
    );
  };

  const save = async () => {
    if (!saving) {
      const end = endTouched ? endInstant(endsAt) : (watch?.ends_at ?? null);
      if (
        end === undefined ||
        (endTouched && end !== null && new Date(end).getTime() <= Date.now())
      ) {
        setInvalidEnd(true);
        return;
      }
      setSaving(true);
      try {
        if (watch) {
          await update({
            id: watch.id,
            changes: {
              ...(maxFailures !== (watch.max_failures === undefined ? 3 : watch.max_failures)
                ? { max_failures: maxFailures }
                : {}),
              ...(reportMode !== (watch.report_mode ?? "changes")
                ? { report_mode: reportMode }
                : {}),
              ...(JSON.stringify(notificationChannels) !==
              JSON.stringify(watch.notification_channels ?? null)
                ? { notification_channels: notificationChannels }
                : {}),
              title: draft.title.trim(),
              instructions: draft.instructions.trim(),
              urgent: draft.urgent,
              interval_minutes: draft.interval,
              exclusions: draft.exclusions.split("\n"),
              ...(draft.agentId !== watch.agent_id ? { agent_id: draft.agentId } : {}),
              environment_id: draft.environmentId,
              pinned_version_id: draft.pinnedVersionId,
              ...(endTouched ? { ends_at: end } : {}),
              ...(reviewSources ? { review_sources: true } : {}),
            },
          });
        } else {
          await create({
            ...(maxFailures !== 3 ? { max_failures: maxFailures } : {}),
            ...(reportMode !== "changes" ? { report_mode: reportMode } : {}),
            ...(notificationChannels !== null
              ? { notification_channels: notificationChannels }
              : {}),
            agent_id: draft.agentId,
            environment_id: draft.environmentId,
            pinned_version_id: draft.pinnedVersionId,
            ends_at: end,
            connection_id: draft.connectionId,
            preset_key: draft.presetKey === CUSTOM ? null : draft.presetKey,
            title: draft.title.trim(),
            instructions: draft.instructions.trim(),
            urgent: draft.urgent,
            interval_minutes: draft.interval,
          });
        }
        if (watch) {
          toast.success(t("saved"));
        } else {
          // Started from an account's menu, the watch would otherwise vanish into
          // a page the person has not seen: say where it lives and where its
          // findings go.
          toast.success(t("created"), {
            description: t("createdWhere"),
            action: onRoutines
              ? undefined
              : { label: t("seeIt"), onClick: () => router.push(`${ROUTES.ROUTINES}?tab=watches`) },
          });
        }
        onOpenChange(false);
      } catch (failure) {
        const problem = submitFailure(failure, { fields: FIELDS }, tErrors);
        setErrors(problem.fields);
        if (!watch) {
          if (
            problem.fields.agent_id ||
            problem.fields.connection_id ||
            problem.fields.title ||
            problem.fields.preset_key
          ) {
            setStep("configure");
          } else if (problem.fields.instructions) {
            setStep("message");
          } else {
            setStep("schedule");
          }
        }
        if (problem.toast) toast.error(problem.toast);
      } finally {
        setSaving(false);
      }
    }
  };

  const ready =
    draft.agentId !== "" &&
    versionValid &&
    !invalidEnd &&
    draft.connectionId !== "" &&
    draft.title.trim() !== "" &&
    draft.instructions.trim() !== "";
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!saving) onOpenChange(next);
      }}
    >
      <RoutineDialogFrame
        title={watch ? t("editTitle") : t("newTitle")}
        description={t("dialogDescription")}
        progress={
          watch
            ? undefined
            : {
                steps: [
                  { id: "configure", label: tt("stepConfigure") },
                  { id: "message", label: tt("stepMessage") },
                  { id: "schedule", label: tt("stepSchedule") },
                ],
                current: step,
              }
        }
        pending={saving}
        disabled={saving}
        footer={
          <WizardNav
            backIsStep={!watch && step !== "configure"}
            backDisabled={saving}
            backLabel={!watch && step !== "configure" ? tt("back") : t("cancel")}
            onBack={() => {
              if (watch || step === "configure") onOpenChange(false);
              else setStep(step === "schedule" ? "message" : "configure");
            }}
            nextLabel={watch ? t("save") : step === "schedule" ? t("create") : tt("continue")}
            onNext={() => {
              if (watch || step === "schedule") void save();
              else setStep(step === "configure" ? "message" : "schedule");
            }}
            nextDisabled={
              watch || step === "schedule"
                ? !ready
                : step === "configure"
                  ? !draft.agentId || !draft.connectionId || !draft.title.trim()
                  : !draft.instructions.trim()
            }
            isLast={Boolean(watch) || step === "schedule"}
            busy={saving}
            busyLabel={watch ? t("save") : tt("creating")}
          />
        }
      >
        <div hidden={!watch && step !== "configure"} className="space-y-4">
          <WatchAgentFields
            agentId={draft.agentId}
            disabled={saving}
            error={errors.agent_id}
            onAgent={(id) => {
              edit({ agentId: id, environmentId: null, pinnedVersionId: null });
              setVersionValid(true);
            }}
          />
          <FormField
            label={t("connection")}
            htmlFor="watch-connection"
            error={errors.connection_id ?? null}
          >
            <Select
              value={draft.connectionId}
              onValueChange={(next) => edit({ connectionId: next, presetKey: CUSTOM })}
              disabled={saving || watch !== undefined}
            >
              <SelectTrigger id="watch-connection">
                <SelectValue placeholder={t("connectionPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {connections.map((each) => (
                  <SelectItem
                    key={each.id}
                    value={each.id}
                    textValue={accountName(each.catalog_key, each.label ?? each.name).name}
                  >
                    <WatchAccount
                      server={each.catalog_key}
                      connectionName={each.label ?? each.name}
                    />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {!watch && (
            <FormField label={t("preset")} htmlFor="watch-preset" error={errors.preset_key ?? null}>
              <Select value={draft.presetKey} onValueChange={pick} disabled={saving}>
                <SelectTrigger id="watch-preset">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={CUSTOM}>{t("custom")}</SelectItem>
                  {offered.map((preset) => (
                    <SelectItem key={preset.key} value={preset.key}>
                      {t(`presets.${preset.key}.title`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
          <FormField label={t("name")} htmlFor="watch-title" error={errors.title ?? null}>
            <Input
              id="watch-title"
              maxLength={120}
              value={draft.title}
              disabled={saving}
              onChange={(event) => edit({ title: event.target.value })}
            />
          </FormField>
        </div>
        <div hidden={!watch && step !== "message"} className={cn("space-y-1.5", watch && "mt-5")}>
          <MarkdownEditor
            id="watch-instructions"
            toolbar={<Label htmlFor="watch-instructions">{t("instructions")}</Label>}
            label={t("instructions")}
            value={draft.instructions}
            disabled={saving}
            invalid={Boolean(errors.instructions)}
            onChange={(instructions) => edit({ instructions })}
            placeholder={t("instructionsPlaceholder")}
            rows={8}
            maxLength={2000}
            describedBy="watch-instructions-hint"
          />
          <p id="watch-instructions-hint" className="text-muted-foreground text-xs leading-relaxed">
            {errors.instructions || t("instructionsHint")}
          </p>
        </div>
        <div hidden={!watch && step !== "schedule"} className={cn("space-y-4", watch && "mt-5")}>
          <FormField
            label={t("howOften")}
            htmlFor="watch-interval"
            error={errors.interval_minutes ?? null}
          >
            <Select
              value={String(draft.interval)}
              onValueChange={(value) => edit({ interval: Number(value) })}
              disabled={saving}
            >
              <SelectTrigger id="watch-interval">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {intervals.map((minutes) => (
                  <SelectItem key={minutes} value={String(minutes)}>
                    {cadenceLabel(minutes, tCadence)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <RoutineOptions
            invalid={
              invalidEnd ||
              !versionValid ||
              Boolean(errors.environment_id) ||
              Boolean(errors.pinned_version_id) ||
              Boolean(environmentsError)
            }
          >
            <WatchExecutionFields
              error={errors.environment_id ?? errors.pinned_version_id}
              agentId={draft.agentId}
              environmentId={draft.environmentId}
              pinnedVersionId={draft.pinnedVersionId}
              onEnvironment={(id) => {
                edit({ environmentId: id, pinnedVersionId: null });
                setVersionValid(true);
              }}
              onVersion={(id) => edit({ pinnedVersionId: id })}
              onVersionValid={setVersionValid}
            />
            {watch && draft.agentId === watch.agent_id && (
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                  <Label htmlFor="watch-review-sources">{t("reviewSources")}</Label>
                  <p className="text-muted-foreground text-xs">{t("reviewSourcesHint")}</p>
                </div>
                <Switch
                  id="watch-review-sources"
                  checked={reviewSources}
                  disabled={saving}
                  onCheckedChange={setReviewSources}
                />
              </div>
            )}
            <FormField
              label={t("reportMode")}
              htmlFor="watch-report-mode"
              description={t("reportModeHint")}
            >
              <Select
                value={reportMode}
                onValueChange={(value) => {
                  if (value === "changes" || value === "every_check") setReportMode(value);
                }}
              >
                <SelectTrigger id="watch-report-mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="changes">{t("changesOnly")}</SelectItem>
                  <SelectItem value="every_check">{t("everyCheck")}</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <FailurePolicyField value={maxFailures} onChange={setMaxFailures} />
            <NotificationChannelsField
              value={notificationChannels}
              onChange={setNotificationChannels}
            />
            <EndsAtField
              value={endsAt}
              invalid={invalidEnd}
              onChange={(value) => {
                setEndsAt(value);
                setEndTouched(true);
                const parsed = endInstant(value);
                setInvalidEnd(
                  parsed === undefined ||
                    (parsed !== null && new Date(parsed).getTime() <= Date.now()),
                );
              }}
            />
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <Label htmlFor="watch-urgent">{t("urgent")}</Label>
                <p className="text-muted-foreground text-xs">{t("urgentHint")}</p>
              </div>
              <Switch
                id="watch-urgent"
                checked={draft.urgent}
                disabled={saving}
                onCheckedChange={(urgent) => edit({ urgent })}
              />
            </div>
            {watch && (
              <FormField
                label={t("exclusions")}
                htmlFor="watch-exclusions"
                description={t("exclusionsHint")}
              >
                <Textarea
                  id="watch-exclusions"
                  rows={3}
                  value={draft.exclusions}
                  disabled={saving}
                  onChange={(event) => edit({ exclusions: event.target.value })}
                />
              </FormField>
            )}
          </RoutineOptions>
        </div>
      </RoutineDialogFrame>
    </Dialog>
  );
}
