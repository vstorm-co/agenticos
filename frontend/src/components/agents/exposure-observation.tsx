"use client";

import { useId, useState } from "react";
import { BrainCircuit, Gauge, Radio } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Switch,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { useModelProviders } from "@/hooks/use-model-providers";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { ChannelObservationConfig } from "@/types/exposures";

const DEFAULTS: ChannelObservationConfig = {
  enabled: false,
  model_profile_id: null,
  instructions: "",
  decision_mode: "llm",
  threshold_percent: 80,
  unmentioned_interval_minutes: 20,
  mentioned_interval_minutes: 1,
};

export function ExposureObservation({
  value,
  disabled,
  onSave,
}: {
  value?: ChannelObservationConfig;
  disabled: boolean;
  onSave: (config: ChannelObservationConfig) => Promise<unknown>;
}) {
  const t = useTranslations("agents");
  const [open, setOpen] = useState(false);
  return (
    <div className="flex items-center gap-3 rounded-lg border p-3">
      <Radio className="text-muted-foreground size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{t("observationTitle")}</p>
        <p className="text-muted-foreground text-xs">{t("observationSummary")}</p>
      </div>
      <Badge variant="outline">{t(value?.enabled ? "observationOn" : "observationOff")}</Badge>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        {t("observationConfigure")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        {open && (
          <ObservationForm
            initial={value ?? DEFAULTS}
            disabled={disabled}
            onSave={async (config) => {
              await onSave(config);
              setOpen(false);
            }}
          />
        )}
      </Dialog>
    </div>
  );
}

function ObservationForm({
  initial,
  disabled,
  onSave,
}: {
  initial: ChannelObservationConfig;
  disabled: boolean;
  onSave: (config: ChannelObservationConfig) => Promise<void>;
}) {
  const t = useTranslations("agents");
  const id = useId();
  const { profiles, profilesStatus } = useModelProviders();
  const { can } = usePermissions();
  const [creatingModel, setCreatingModel] = useState(false);
  const [original] = useState(() => ({
    ...initial,
    instructions: initial.instructions || t("observationDefaultInstructions"),
  }));
  const [config, setConfig] = useState(original);
  const [coldInterval, setColdInterval] = useState(String(initial.unmentioned_interval_minutes));
  const [warmInterval, setWarmInterval] = useState(String(initial.mentioned_interval_minutes));
  const [threshold, setThreshold] = useState(initial.threshold_percent ?? 80);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const changed =
    JSON.stringify(config) !== JSON.stringify(original) ||
    coldInterval !== String(initial.unmentioned_interval_minutes) ||
    warmInterval !== String(initial.mentioned_interval_minutes) ||
    threshold !== (initial.threshold_percent ?? 80);
  return (
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
      <DialogHeader>
        <DialogTitle id={`${id}-title`}>{t("observationTitle")}</DialogTitle>
        <DialogDescription>{t("observationDescription")}</DialogDescription>
      </DialogHeader>
      <form
        aria-labelledby={`${id}-title`}
        className="space-y-5"
        onSubmit={async (event) => {
          event.preventDefault();
          if (config.enabled && !config.model_profile_id) {
            setError(t("observationRequired"));
            return;
          }
          setError(null);
          setSaving(true);
          try {
            await onSave({
              ...config,
              threshold_percent: threshold,
              unmentioned_interval_minutes: Number(coldInterval),
              mentioned_interval_minutes: Number(warmInterval),
            });
          } catch {
            setError(t("observationSaveFailed"));
          } finally {
            setSaving(false);
          }
        }}
      >
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor={`${id}-enabled`}>{t("observationEnable")}</Label>
          <Switch
            id={`${id}-enabled`}
            checked={config.enabled}
            disabled={disabled || saving}
            onCheckedChange={(enabled) => setConfig({ ...config, enabled })}
          />
        </div>
        <fieldset disabled={disabled || saving} className="space-y-4">
          <legend className="mb-2 text-sm font-medium">{t("observationDecisionModel")}</legend>
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-engine`}>{t("observationEngine")}</Label>
            <Select
              value={config.decision_mode ?? "llm"}
              onValueChange={(mode) => {
                if (mode === "llm" || mode === "native")
                  setConfig({ ...config, decision_mode: mode, model_profile_id: null });
              }}
            >
              <SelectTrigger id={`${id}-engine`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="llm">
                  <span className="flex items-center gap-2">
                    <BrainCircuit className="size-4" aria-hidden />
                    {t("observationLlm")}
                  </span>
                </SelectItem>
                <SelectItem value="native">
                  <span className="flex items-center gap-2">
                    <Gauge className="size-4" aria-hidden />
                    {t("observationNative")}
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <ModelProfilePicker
            profiles={profiles}
            profilesStatus={profilesStatus}
            purpose={config.decision_mode === "native" ? "decision" : "chat"}
            value={config.model_profile_id}
            allowAdd={can(Perm.connectionsManage)}
            disabled={disabled || saving}
            onCreationPendingChange={setCreatingModel}
            onChange={(model_profile_id) => setConfig({ ...config, model_profile_id })}
          />
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor={`${id}-threshold`}>{t("observationThreshold")}</Label>
              <span className="shrink-0 text-sm font-medium tabular-nums">{threshold}%</span>
            </div>
            <input
              id={`${id}-threshold`}
              name="threshold"
              type="range"
              min={0}
              max={100}
              step={1}
              value={threshold}
              aria-valuetext={`${threshold}%`}
              aria-describedby={`${id}-threshold-hint`}
              className="accent-foreground focus-visible:outline-ring h-10 w-full cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              onChange={(event) => setThreshold(event.target.valueAsNumber)}
            />
            <p id={`${id}-threshold-hint`} className="text-muted-foreground text-xs">
              {t(
                config.decision_mode === "native"
                  ? "observationProbabilityHint"
                  : "observationScoreHint",
              )}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-instructions`}>{t("observationFocus")}</Label>
            <Textarea
              id={`${id}-instructions`}
              name="instructions"
              maxLength={8000}
              value={config.instructions}
              className="min-h-56"
              onChange={(event) => setConfig({ ...config, instructions: event.target.value })}
            />
          </div>
          <fieldset className="grid gap-3 sm:grid-cols-2">
            <legend className="mb-2 text-sm font-medium">{t("observationTiming")}</legend>
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-cold`}>{t("observationUnmentioned")}</Label>
              <Input
                id={`${id}-cold`}
                aria-describedby={`${id}-cold-hint`}
                name="unmentionedInterval"
                type="number"
                min={1}
                max={1440}
                required
                value={coldInterval}
                onChange={(event) => setColdInterval(event.target.value)}
              />
              <p id={`${id}-cold-hint`} className="text-muted-foreground text-xs">
                {t("observationUnmentionedHint")}
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-warm`}>{t("observationMentioned")}</Label>
              <Input
                id={`${id}-warm`}
                aria-describedby={`${id}-warm-hint`}
                name="mentionedInterval"
                type="number"
                min={1}
                max={1440}
                required
                value={warmInterval}
                onChange={(event) => setWarmInterval(event.target.value)}
              />
              <p id={`${id}-warm-hint`} className="text-muted-foreground text-xs">
                {t("observationMentionedHint")}
              </p>
            </div>
          </fieldset>
          <p className="bg-muted/40 text-muted-foreground rounded-lg p-3 text-xs leading-relaxed">
            {t("observationTimingHint")}
          </p>
          <p className="text-muted-foreground text-xs">{t("observationAllChannels")}</p>
          <p className="bg-muted/40 text-muted-foreground rounded-lg p-3 text-xs leading-relaxed">
            {t("observationAuthorityHint")}
          </p>
        </fieldset>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button type="submit" disabled={!changed || disabled || saving || creatingModel}>
            {t("observationSave")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
