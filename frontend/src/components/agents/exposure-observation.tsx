"use client";

import { useId, useState } from "react";
import { Radio } from "lucide-react";
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
  Textarea,
} from "@/components/ui";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { useModelProviders } from "@/hooks/use-model-providers";
import type { ChannelObservationConfig } from "@/types/exposures";

const DEFAULTS: ChannelObservationConfig = {
  enabled: false,
  model_profile_id: null,
  instructions: "",
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
  const [config, setConfig] = useState(initial);
  const [coldInterval, setColdInterval] = useState(String(initial.unmentioned_interval_minutes));
  const [warmInterval, setWarmInterval] = useState(String(initial.mentioned_interval_minutes));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
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
          <ModelProfilePicker
            emptyLabel={t("observationDecisionModel")}
            profiles={profiles}
            profilesStatus={profilesStatus}
            compact
            value={config.model_profile_id}
            allowAdd={false}
            onChange={(model_profile_id) => setConfig({ ...config, model_profile_id })}
          />
          <div className="space-y-1.5">
            <Label htmlFor={`${id}-instructions`}>{t("observationFocus")}</Label>
            <Textarea
              id={`${id}-instructions`}
              name="instructions"
              maxLength={8000}
              value={config.instructions}
              className="min-h-28"
              onChange={(event) => setConfig({ ...config, instructions: event.target.value })}
            />
          </div>
          <fieldset className="grid gap-3 sm:grid-cols-2">
            <legend className="mb-2 text-sm font-medium">{t("observationTiming")}</legend>
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-cold`}>{t("observationUnmentioned")}</Label>
              <Input
                id={`${id}-cold`}
                name="unmentionedInterval"
                type="number"
                min={1}
                max={1440}
                required
                value={coldInterval}
                onChange={(event) => setColdInterval(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-warm`}>{t("observationMentioned")}</Label>
              <Input
                id={`${id}-warm`}
                name="mentionedInterval"
                type="number"
                min={1}
                max={1440}
                required
                value={warmInterval}
                onChange={(event) => setWarmInterval(event.target.value)}
              />
            </div>
          </fieldset>
          <p className="text-muted-foreground text-xs">{t("observationTimingHint")}</p>
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
          <Button type="submit" disabled={disabled || saving}>
            {t("observationSave")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
