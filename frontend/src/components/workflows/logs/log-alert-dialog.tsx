"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { MemberPicker } from "@/components/orgs/member-picker";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useMembers, useWorkflowLogAlerts } from "@/hooks";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import {
  LOG_ALERT_NAME_MAX,
  LOG_ALERT_TEXT_MAX,
  LOG_ALERT_THRESHOLD_MAX,
  LOG_ALERT_WINDOWS,
  type LogAlertAudience,
  type LogAlertRule,
  type LogAlertWindow,
} from "@/lib/workflows/types";
import { useOrgStore } from "@/stores";
import { toast } from "sonner";

// Not a step id, so a step can never be mistaken for the choice of none.
const ANY = "\u0000any";
const AUDIENCES: LogAlertAudience[] = ["admins", "owner", "chosen"];
const AUDIENCE_KEY: Record<LogAlertAudience, string> = {
  admins: "alertAudienceAdmins",
  owner: "alertAudienceOwner",
  chosen: "alertAudienceChosen",
};

export interface LogAlertChoices {
  /** The steps that log, as [id, name]. */
  steps: [string, string][];
  /** Per step, the outcomes its quick log writes. */
  stepPorts: Map<string, string[]>;
  /** A port's label by id. */
  labels: Map<string, string>;
  /**
   * Per step the live version logs, the outcomes its quick log writes - what an alert
   * rule is judged against; null when the workflow has no live version.
   */
  livePorts: Map<string, string[]> | null;
}

/**
 * Adding a rule on a workflow's log, or changing one: what to count (the step,
 * the outcomes, text in the message), how many in how long, and who hears of it.
 * Mounted only while open, so each opening starts from the rule as it stands.
 * The outcomes offered are the ones the chosen step's quick log writes, which is
 * what the server accepts.
 */
export function LogAlertDialog({
  workflowId,
  rule,
  choices,
  onClose,
}: {
  workflowId: string;
  /** The rule being changed, or null to add one. */
  rule: LogAlertRule | null;
  choices: LogAlertChoices;
  onClose: () => void;
}) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const { create, update } = useWorkflowLogAlerts(workflowId);
  /* v8 ignore next -- the selector never runs: every test here mocks the store */
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members } = useMembers(activeOrgId ?? "");
  const [name, setName] = useState(rule?.name ?? "");
  const [step, setStep] = useState(rule?.node_instance_id ?? ANY);
  const [outcomes, setOutcomes] = useState<string[]>(rule?.outcomes ?? []);
  const [text, setText] = useState(rule?.message_contains ?? "");
  const [threshold, setThreshold] = useState(String(rule?.threshold ?? 5));
  const [windowMinutes, setWindowMinutes] = useState(String(rule?.window_minutes ?? 15));
  const [audience, setAudience] = useState<LogAlertAudience[]>(rule?.audience ?? ["owner"]);
  const [userIds, setUserIds] = useState<string[]>(rule?.user_ids ?? []);
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  // What is wrong with the form is said once a save has been tried, not on opening.
  const [tried, setTried] = useState(false);
  const [problems, setProblems] = useState<Readonly<Record<string, string>>>({});
  const pending = create.isPending || update.isPending;

  // A rule edited after its step left the graph keeps naming it, so it stays visible.
  const stepOptions: [string, string][] =
    step === ANY || choices.steps.some(([id]) => id === step)
      ? choices.steps
      : [...choices.steps, [step, step]];
  const anyStep = [...new Set([...choices.stepPorts.values()].flat())];
  const offered = step === ANY ? anyStep : (choices.stepPorts.get(step) ?? outcomes);
  // Stored outcomes the step no longer writes stay listed (checked), so saving
  // shows the server's refusal rather than silently dropping them.
  const portOptions = [...offered, ...outcomes.filter((port) => !offered.includes(port))];

  const toggle = <T extends string>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];

  const limit = Number(threshold);
  const invalid: Record<string, string> = {};
  if (name.trim() === "") invalid.name = t("alertNeedsName");
  if (outcomes.length === 0) invalid.outcomes = t("alertNeedsOutcome");
  if (!Number.isInteger(limit) || limit < 1 || limit > LOG_ALERT_THRESHOLD_MAX) {
    invalid.threshold = t("alertThresholdRange", { max: LOG_ALERT_THRESHOLD_MAX });
  }
  if (audience.length === 0) invalid.audience = t("alertNeedsAudience");
  else if (audience.includes("chosen") && userIds.length === 0) {
    invalid.audience = t("alertNeedsPeople");
  }
  const shown = tried ? { ...invalid, ...problems } : problems;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setTried(true);
    if (Object.keys(invalid).length > 0) {
      setProblems(invalid);
      return;
    }
    const input = {
      name: name.trim(),
      outcomes,
      node_instance_id: step === ANY ? null : step,
      message_contains: text.trim() === "" ? null : text.trim(),
      threshold: limit,
      window_minutes: Number(windowMinutes) as LogAlertWindow,
      audience,
      // Ids are only read with `chosen`; dropping the audience drops the list.
      user_ids: audience.includes("chosen") ? userIds : [],
      enabled,
    };
    try {
      if (rule === null) await create.mutateAsync(input);
      else await update.mutateAsync({ ruleId: rule.id, patch: input });
      onClose();
    } catch (error) {
      const failure = submitFailure(
        error,
        {
          fields: [
            "name",
            "outcomes",
            "node_instance_id",
            "message_contains",
            "threshold",
            "window_minutes",
            "audience",
            "user_ids",
          ],
          identifiedBy: "name",
        },
        tErrors,
      );
      setProblems(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    }
  };

  return (
    // Mounted only while open, so the one change of openness it can report is closing.
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>{rule === null ? t("alertNew") : t("alertEdit")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <FormField
            label={t("alertName")}
            htmlFor="log-alert-name"
            description={t("alertNameHint")}
            error={shown.name}
          >
            <Input
              id="log-alert-name"
              value={name}
              maxLength={LOG_ALERT_NAME_MAX}
              placeholder={t("alertNamePlaceholder")}
              onChange={(event) => {
                setName(event.target.value);
                setProblems({});
              }}
            />
          </FormField>

          <div className="space-y-1.5">
            <Label htmlFor="log-alert-step">{t("alertStep")}</Label>
            <Select
              value={step}
              onValueChange={(next) => {
                setStep(next);
                // Outcomes the new step does not write cannot be asked for.
                const allowed = next === ANY ? anyStep : (choices.stepPorts.get(next) ?? []);
                setOutcomes((current) => current.filter((port) => allowed.includes(port)));
                setProblems({});
              }}
            >
              <SelectTrigger id="log-alert-step" aria-label={t("alertStep")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>{t("logFilterAnyStep")}</SelectItem>
                {stepOptions.map(([id, label]) => (
                  <SelectItem key={id} value={id}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">{t("alertStepHint")}</p>
            {shown.node_instance_id !== undefined && (
              <p role="alert" className="text-destructive text-xs">
                {shown.node_instance_id}
              </p>
            )}
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("alertOutcomes")}</legend>
            <p className="text-muted-foreground text-xs">{t("alertOutcomesHint")}</p>
            <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
              {portOptions.map((port) => (
                <div key={port} className="flex items-center gap-2.5">
                  <Checkbox
                    id={`log-alert-outcome-${port}`}
                    checked={outcomes.includes(port)}
                    onCheckedChange={() => {
                      setOutcomes(toggle(outcomes, port));
                      setProblems({});
                    }}
                  />
                  <Label htmlFor={`log-alert-outcome-${port}`} className="text-sm font-normal">
                    {choices.labels.get(port) ?? port}
                  </Label>
                </div>
              ))}
            </div>
            {shown.outcomes !== undefined && (
              <p role="alert" className="text-destructive text-xs">
                {shown.outcomes}
              </p>
            )}
          </fieldset>

          <FormField
            label={t("alertText")}
            htmlFor="log-alert-text"
            description={t("alertTextHint")}
            error={shown.message_contains}
          >
            <Input
              id="log-alert-text"
              value={text}
              maxLength={LOG_ALERT_TEXT_MAX}
              onChange={(event) => {
                setText(event.target.value);
                setProblems({});
              }}
            />
          </FormField>

          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={t("alertThreshold")}
              htmlFor="log-alert-threshold"
              description={t("alertThresholdHint")}
              error={shown.threshold}
            >
              <Input
                id="log-alert-threshold"
                type="number"
                min={1}
                max={LOG_ALERT_THRESHOLD_MAX}
                step={1}
                value={threshold}
                onChange={(event) => {
                  setThreshold(event.target.value);
                  setProblems({});
                }}
              />
            </FormField>
            <div className="space-y-1.5">
              <Label htmlFor="log-alert-window">{t("alertWindow")}</Label>
              <Select value={windowMinutes} onValueChange={setWindowMinutes}>
                <SelectTrigger id="log-alert-window" aria-label={t("alertWindow")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LOG_ALERT_WINDOWS.map((minutes) => (
                    <SelectItem key={minutes} value={String(minutes)}>
                      {t(`alertWindows.${minutes}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("alertWindowHint")}</p>
              {shown.window_minutes !== undefined && (
                <p role="alert" className="text-destructive text-xs">
                  {shown.window_minutes}
                </p>
              )}
            </div>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("alertAudience")}</legend>
            <p className="text-muted-foreground text-xs">{t("alertAudienceHint")}</p>
            <div className="grid gap-x-6 gap-y-2 sm:grid-cols-3">
              {AUDIENCES.map((who) => (
                <div key={who} className="flex items-center gap-2.5">
                  <Checkbox
                    id={`log-alert-audience-${who}`}
                    checked={audience.includes(who)}
                    onCheckedChange={() => {
                      setAudience(toggle(audience, who));
                      setProblems({});
                    }}
                  />
                  <Label htmlFor={`log-alert-audience-${who}`} className="text-sm font-normal">
                    {t(AUDIENCE_KEY[who])}
                  </Label>
                </div>
              ))}
            </div>
            {audience.includes("chosen") && (
              <MemberPicker
                members={members}
                selected={userIds}
                onToggle={(id) => setUserIds(toggle(userIds, id))}
                label={(count) => t("alertPeopleChosen", { count })}
                scope={t("alertAudienceChosen")}
              />
            )}
            {(shown.audience ?? shown.user_ids) !== undefined && (
              <p role="alert" className="text-destructive text-xs">
                {shown.audience ?? shown.user_ids}
              </p>
            )}
          </fieldset>

          <div className="flex items-center gap-2">
            <Switch id="log-alert-enabled" checked={enabled} onCheckedChange={setEnabled} />
            <Label htmlFor="log-alert-enabled" className="text-sm">
              {t("alertEnabled")}
            </Label>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("alertCancel")}
            </Button>
            <Button type="submit" disabled={pending}>
              {t("alertSave")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
