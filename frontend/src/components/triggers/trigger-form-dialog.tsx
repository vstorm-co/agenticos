"use client";

import { useState } from "react";
import { CalendarClock, Cog, MessageSquare, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  Label,
  MarkdownEditor,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsList,
  TabsTrigger,
  WizardNav,
  WizardSteps,
  type WizardStep,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { DEFAULT_ENV, EnvironmentField } from "@/components/triggers/environment-field";
import { EventSourceMark } from "@/components/triggers/event-source-mark";
import { TriggerTemplatePicker } from "@/components/triggers/trigger-template-picker";
import { SecretRevealField } from "@/components/triggers/secret-reveal-field";
import { useAgentEnvironments, useAgents } from "@/hooks";
import { useTriggers } from "@/hooks/use-triggers";
import { useAgentSelectionStore } from "@/stores";
import {
  type CronFrequency,
  eventFilterConfig,
  FILTER_KEYS,
  type IntervalUnit,
  intervalToUnit,
  parseCron,
  unitToSeconds,
  WEEKDAYS,
  weekdayKey,
} from "@/lib/trigger-format";
import type {
  EventSource,
  ScheduleKind,
  Trigger,
  TriggerCreate,
  TriggerCreated,
  TriggerType,
  TriggerUpdate,
} from "@/types/triggers";
import type { TriggerTemplate } from "@/types/trigger-templates";
import {
  DIALOG_BROAD,
  DIALOG_CONFIRM,
  DIALOG_FORM,
  DIALOG_FRAMED,
  DIALOG_SCROLL,
} from "@/lib/dialog-sizes";

/** The backend's floor for a webhook secret; the generator comfortably clears it. */
const MIN_SECRET = 16;

/** A strong random signing secret, so nobody has to invent one. */
function generateSecret(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * The create wizard's steps. A schedule walks configure → message → schedule;
 * an event walks event → configure → message. "configure" carries the short
 * fields (agent, name, environment) and "message" only the prompt - a message
 * is often long, and sharing a step would push everything else off screen.
 */
type WizardStepId = "event" | "configure" | "message" | "schedule";

/** The repeat options, as translation keys so the catalog check can see them. */
const CRON_FREQUENCIES: readonly { value: CronFrequency; key: string }[] = [
  { value: "daily", key: "freqDaily" },
  { value: "everyNDays", key: "freqEveryNDays" },
  { value: "weekly", key: "freqWeekly" },
  { value: "monthly", key: "freqMonthly" },
  { value: "advanced", key: "freqAdvanced" },
];

/** A bounded integer from a form string, or the fallback when it is not one. */
function clampInt(value: string, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

// The most of any unit "Run every" accepts. The server's ceiling is the int32
// the column stores; this one exists for the reader - 999 days is already a
// cadence nobody scheduled on purpose, and a smaller bound makes the field's
// error message concrete instead of quoting a 10-digit number.
const INTERVAL_MAX = 999;

/** Whether the "Run every" count is a whole number the schedule can take. */
function intervalCountValid(value: string): boolean {
  return /^\d+$/.test(value) && Number(value) >= 1 && Number(value) <= INTERVAL_MAX;
}

interface TriggerFormDialogProps {
  /**
   * The agent the trigger belongs to, or null when the surface has no agent in
   * context - the chat sidebar's New schedule/trigger - in which case the form
   * offers a picker over the published agents, seeded with the user's default.
   */
  agentId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The trigger to edit, or null/undefined to create a new one. */
  trigger?: Trigger | null;
  /** Which concept a new trigger starts on. Ignored when editing. */
  initialType?: TriggerType;
}

/**
 * The one form behind creating and editing a trigger, on every surface.
 *
 * Creating walks the same stepper chrome as the KB sync-source wizard: a
 * schedule defines the task then its cadence, an API trigger picks what
 * fires it then the task. Editing keeps a single panel - see below.
 *
 * A trigger's shape is set once: creating chooses schedule-or-event and its
 * cadence or source, and editing may change only the prompt and the environment -
 * the shape controls are read-only, because switching an interval to cron or
 * repointing an event is a different trigger, made by deleting this one and
 * creating that. That mirrors exactly what the server's shape CHECK and its
 * update schema allow, so the form never offers an edit the API will refuse.
 */
export function TriggerFormDialog({
  agentId,
  open,
  onOpenChange,
  trigger = null,
  initialType = "schedule",
}: TriggerFormDialogProps) {
  const t = useTranslations("triggers");
  const editing = trigger !== null;

  // The registry list backs the picker when the caller brought no agent. It is
  // the same cached query every agent surface reads, so on the surfaces that
  // already know whom they are scheduling this costs nothing new.
  const { agents } = useAgents();
  const defaultAgentId = useAgentSelectionStore((state) => state.defaultAgentId);
  // Only agents the caller may actually run: a published version to run, and a
  // `can_run` that resolves the caller's role scope plus any run grant. Seeding
  // the default from this set never points at an agent the create would refuse.
  const runnable = agents.filter((agent) => agent.status === "published" && agent.can_run);
  const [pickedAgentId, setPickedAgentId] = useState("");
  // The user's starred default, or the first published agent, the moment the
  // list arrives - the same resolution the chat's own picker makes.
  const seededAgentId =
    pickedAgentId || (runnable.find((agent) => agent.id === defaultAgentId) ?? runnable[0])?.id;
  const effectiveAgentId = agentId ?? seededAgentId ?? null;

  const { create, update, runNow, rotateSecret } = useTriggers(effectiveAgentId);
  const { environments } = useAgentEnvironments(effectiveAgentId);
  const namedEnvironments = environments.filter((environment) => !environment.is_default);
  // Named on the default item rather than offered as a second row: binding to
  // "the default" is not the same choice as pinning to whichever row is default
  // today, but a list that would not say which one that is read as an
  // environment missing (#1070).
  const defaultEnvironment = environments.find((environment) => environment.is_default) ?? null;

  // A trigger's kind is fixed once the dialog opens: editing keeps the row's type,
  // and creating takes whichever kind the entry point chose - "New schedule" opens
  // this on a schedule, the portal grid's "Advanced: API trigger" hatch on an
  // event. There is no in-dialog switch, because event triggers are created from
  // the portal grid by default, not this raw form.
  const type = trigger?.trigger_type ?? initialType;
  // Creating walks the KB-wizard steps; editing has no steps - the shape is
  // fixed, so its few live fields fit one panel.
  const [step, setStep] = useState<WizardStepId>(type === "event" ? "event" : "configure");
  const [prompt, setPrompt] = useState(trigger?.prompt ?? "");
  const [name, setName] = useState(trigger?.name ?? "");
  const [environmentId, setEnvironmentId] = useState(trigger?.environment_id ?? DEFAULT_ENV);

  const seed = trigger?.interval_seconds
    ? intervalToUnit(trigger.interval_seconds)
    : { unit: "minutes" as IntervalUnit, count: 15 };
  // A new schedule opens on "daily at 09:00" - the cadence most schedules
  // actually want, and the one the DAILY 09:00 preset pill names - so Create
  // is one step away with nothing touched. Editing keeps the row's own kind.
  const [scheduleKind, setScheduleKind] = useState<ScheduleKind>(trigger?.schedule_kind ?? "cron");
  const [intervalCount, setIntervalCount] = useState(String(seed.count));
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>(seed.unit);

  // The "at a set time" builder composes a cron expression from plain choices - a
  // time and how it repeats - so nobody has to write crontab. Editing a cron
  // schedule seeds the builder back from its expression (falling to "advanced"
  // for one no preset represents); a new schedule opens on 09:00 daily, which is
  // exactly the `0 9 * * *` the old raw field seeded.
  const cronSeed =
    trigger?.schedule_kind === "cron" && trigger.cron_expression
      ? parseCron(trigger.cron_expression)
      : null;
  const [cronFreq, setCronFreq] = useState<CronFrequency>(cronSeed?.freq ?? "daily");
  const [cronTime, setCronTime] = useState(cronSeed?.time ?? "09:00");
  const [cronEveryDays, setCronEveryDays] = useState(cronSeed?.everyDays ?? "2");
  const [cronWeekdays, setCronWeekdays] = useState<number[]>(cronSeed?.weekdays ?? [1]);
  const [cronDayOfMonth, setCronDayOfMonth] = useState(cronSeed?.dayOfMonth ?? "1");
  const [cronAdvanced, setCronAdvanced] = useState(trigger?.cron_expression ?? "0 9 * * *");
  // Whether the user actually touched a cadence control. Seeding the editor from
  // a non-round interval rounds it (`intervalToUnit`), so comparing a rebuilt
  // cadence to the original would report a change on a prompt-only edit and reset
  // the clock; the cadence is sent only when this says it was really edited.
  const [cadenceTouched, setCadenceTouched] = useState(false);
  // Which seeded template a new schedule started from, or null for "from
  // scratch" (the default). Only tracked to light the picked card; the fields it
  // prefilled stay freely editable below.
  const [templateKey, setTemplateKey] = useState<string | null>(null);

  // `webhook` for a new one, not `github`: the portal grid is the way to a GitHub
  // or Gmail trigger now, and this form is reached from the "API trigger" card -
  // your own code posting signed JSON. Defaulting to GitHub opened that card on
  // "Fires on: a GitHub issue" with a GitHub template picked under it, for
  // somebody who had just chosen the opposite. An edit reads the row.
  const [eventSource, setEventSource] = useState<EventSource>(trigger?.event_source ?? "webhook");
  const [secret, setSecret] = useState("");
  // Two generic substring filters; what they mean is the source's business - a
  // subject and sender for email - so the keys are mapped in `buildCreate` and
  // the labels in `EventFields`. Editing seeds them from the row's own filter,
  // so a saved `subject_contains` comes back as the value it was, not a blank
  // that would read as "no filter".
  const seededFilter = (index: number): string => {
    if (!trigger?.event_source) return "";
    const key = FILTER_KEYS[trigger.event_source]?.[index];
    const value = key ? trigger.event_config[key] : undefined;
    return typeof value === "string" ? value : "";
  };
  const [filterA, setFilterA] = useState(seededFilter(0));
  const [filterB, setFilterB] = useState(seededFilter(1));
  // The event trigger just created, held so the dialog can show its webhook URL
  // and its signing secret to paste into the provider before it closes - the
  // two things an event trigger needs that a schedule does not. The created
  // type, not Trigger: `reveal_secret` exists only on the create response, and
  // losing it here is losing it forever (no read ever returns it).
  const [created, setCreated] = useState<TriggerCreated | null>(null);

  const pending = create.isPending || update.isPending;

  /** The cron expression the builder's current choices compile to. `everyNDays`
   *  is deliberately absent: it is fired as an interval, not cron (see
   *  `scheduleCadence`), because no cron day-of-month form repeats continuously. */
  function composeCron(): string {
    if (cronFreq === "advanced") return cronAdvanced.trim();
    const [rawHour, rawMinute] = cronTime.split(":");
    const hour = clampInt(rawHour ?? "", 0, 23, 9);
    const minute = clampInt(rawMinute ?? "", 0, 59, 0);
    if (cronFreq === "weekly") {
      const days = cronWeekdays.length ? [...cronWeekdays].sort((a, b) => a - b).join(",") : "1";
      return `${minute} ${hour} * * ${days}`;
    }
    if (cronFreq === "monthly") {
      return `${minute} ${hour} ${clampInt(cronDayOfMonth, 1, 31, 1)} * *`;
    }
    return `${minute} ${hour} * * *`;
  }

  function toggleWeekday(value: number) {
    setCronWeekdays((current) =>
      current.includes(value) ? current.filter((day) => day !== value) : [...current, value],
    );
  }

  /** Prefill what the template's mode can use, still editable below: the
   *  message always, the cadence only from a schedule template - an event
   *  template has none. */
  function applyTemplate(template: TriggerTemplate) {
    setTemplateKey(template.key);
    setPrompt(template.prompt);
    const cadence = template.suggested_cadence;
    if (!cadence) return;
    setCadenceTouched(true);
    if (cadence.schedule_kind === "cron" && cadence.cron_expression) {
      const parsed = parseCron(cadence.cron_expression);
      setScheduleKind("cron");
      setCronFreq(parsed.freq);
      setCronTime(parsed.time);
      setCronEveryDays(parsed.everyDays);
      setCronWeekdays(parsed.weekdays);
      setCronDayOfMonth(parsed.dayOfMonth);
      setCronAdvanced(cadence.cron_expression);
    } else if (cadence.interval_seconds) {
      const { unit, count } = intervalToUnit(cadence.interval_seconds);
      setScheduleKind("interval");
      setIntervalUnit(unit);
      setIntervalCount(String(count));
    }
  }

  /** Clear the template prefill and return to a blank message. */
  function scratchTemplate() {
    setTemplateKey(null);
    setPrompt("");
  }

  /** Set the cadence controls to a quick preset; they stay editable below it. */
  function applyPreset(preset: CadencePreset) {
    setCadenceTouched(true);
    if (preset.kind === "interval") {
      setScheduleKind("interval");
      setIntervalUnit(preset.unit);
      setIntervalCount(String(preset.count));
      return;
    }
    setScheduleKind("cron");
    setCronFreq(preset.freq);
    setCronTime(preset.time);
    if (preset.freq === "weekly") setCronWeekdays(preset.weekdays);
  }

  /** Wraps a cadence setter so editing any cadence control flips `cadenceTouched`. */
  function onCadence<T>(setter: (value: T) => void): (value: T) => void {
    return (value) => {
      setCadenceTouched(true);
      setter(value);
    };
  }

  /** The cadence fields a schedule sends - on create, and on a cadence edit. */
  function scheduleCadence(): Pick<
    TriggerCreate,
    "schedule_kind" | "interval_seconds" | "cron_expression"
  > {
    if (scheduleKind === "cron") {
      // "Every N days" is an interval, not cron: `*/N` on day-of-month steps
      // within a month and resets at each boundary, so an every-2-days schedule
      // could fire Jan 31 then Feb 1. An interval repeats continuously, which is
      // what the preset promises.
      if (cronFreq === "everyNDays") {
        return {
          schedule_kind: "interval",
          interval_seconds: unitToSeconds("days", clampInt(cronEveryDays, 1, 31, 1)),
        };
      }
      return { schedule_kind: "cron", cron_expression: composeCron() };
    }
    return {
      schedule_kind: "interval",
      interval_seconds: unitToSeconds(intervalUnit, clampInt(intervalCount, 1, INTERVAL_MAX, 1)),
    };
  }

  function buildCreate(): TriggerCreate {
    const base = {
      prompt,
      name: name.trim() || null,
      trigger_type: type,
      environment_id: environmentId === DEFAULT_ENV ? null : environmentId,
    };
    if (type === "schedule") {
      return { ...base, ...scheduleCadence() };
    }
    return {
      ...base,
      event_source: eventSource,
      event_secret: secret,
      event_config: eventFilterConfig(eventSource, [filterA, filterB]),
    };
  }

  async function submit() {
    try {
      if (editing) {
        // Only the fields that actually changed: the server applies exactly what
        // it is sent, so echoing `environment_id` back on a prompt-only edit
        // would overwrite an environment somebody rebound in between.
        const patch: TriggerUpdate = {};
        if (prompt !== trigger.prompt) patch.prompt = prompt;
        const nextName = name.trim() || null;
        if (nextName !== (trigger.name ?? null)) patch.name = nextName;
        const env = environmentId === DEFAULT_ENV ? null : environmentId;
        if (env !== (trigger.environment_id ?? null)) patch.environment_id = env;
        // A schedule's cadence, only when a cadence control was actually touched.
        // The server recomputes next_fire_at on any cadence field it receives, so
        // echoing the cadence on a prompt-only edit would needlessly reset the
        // clock - and a non-round interval, rounded when it seeded the editor,
        // would even be sent back changed.
        if (trigger.trigger_type === "schedule" && cadenceTouched) {
          Object.assign(patch, scheduleCadence());
        }
        // An event's filter is editable in place (the source and secret are
        // not); sent only when a value changed, and as `{}` when both were
        // cleared - which the server reads as "fire on anything signed".
        if (trigger.trigger_type === "event" && trigger.event_source) {
          const keys = FILTER_KEYS[trigger.event_source] ?? [];
          const changed = keys.some(
            (key, index) => ([filterA, filterB][index]?.trim() ?? "") !== seededFilter(index),
          );
          if (changed) {
            patch.event_config = eventFilterConfig(trigger.event_source, [filterA, filterB]) ?? {};
          }
        }
        await update.mutateAsync({ triggerId: trigger.id, patch });
        onOpenChange(false);
      } else {
        const result = await create.mutateAsync(buildCreate());
        // A new event trigger stays open on its webhook URL - the caller has to
        // paste it into the provider or nothing will ever fire it. A schedule
        // has nothing more to do, so it closes.
        if (result.trigger_type === "event") setCreated(result);
        else onOpenChange(false);
      }
    } catch {
      // The hook toasts the server's refusal; the dialog stays open so nothing
      // typed is lost - the usual reason to be here is a value one edit away.
    }
  }

  // A preset always composes a valid expression; only the raw "advanced" escape
  // hatch can be left empty, so it is the one cron shape worth guarding.
  const cronValid = cronFreq !== "advanced" || cronAdvanced.trim().length > 0;
  const scheduleValid = scheduleKind === "cron" ? cronValid : intervalCountValid(intervalCount);
  const taskValid = prompt.trim().length > 0 && effectiveAgentId !== null;
  // Editing a schedule can change its cadence, so the cadence is guarded then
  // too; an event edit has no cadence and only its prompt/name to check.
  const canSubmit = taskValid && (type !== "schedule" || scheduleValid) && !pending;

  const steps: WizardStep[] =
    type === "schedule"
      ? [
          { id: "configure", label: t("stepConfigure"), icon: Cog },
          { id: "message", label: t("stepMessage"), icon: MessageSquare },
          { id: "schedule", label: t("stepSchedule"), icon: CalendarClock },
        ]
      : [
          { id: "event", label: t("stepEvent"), icon: Zap },
          { id: "configure", label: t("stepConfigure"), icon: Cog },
          { id: "message", label: t("stepMessage"), icon: MessageSquare },
        ];
  const stepIdx = steps.findIndex((entry) => entry.id === step);
  const isLastStep = stepIdx === steps.length - 1;
  // Each step gates on its own concern, so a Continue can never outrun what the
  // final Create would refuse.
  const canAdvance =
    step === "configure"
      ? effectiveAgentId !== null
      : step === "message"
        ? prompt.trim().length > 0
        : step === "schedule"
          ? scheduleValid
          : secret.length >= MIN_SECRET;
  const onFirstStep = stepIdx === 0;

  function handleNext() {
    if (!canAdvance || pending) return;
    if (isLastStep) {
      void submit();
      return;
    }
    setStep(steps[stepIdx + 1]!.id as WizardStepId);
  }

  function handleBack() {
    if (stepIdx > 0) setStep(steps[stepIdx - 1]!.id as WizardStepId);
  }

  if (created !== null) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className={DIALOG_CONFIRM}>
          <DialogHeader>
            <DialogTitle>{t("createdTitle")}</DialogTitle>
            <DialogDescription>{t("createdDescription")}</DialogDescription>
          </DialogHeader>
          {created.webhook_url && <WebhookField url={created.webhook_url} />}
          {/* The secret, shown beside the URL it belongs with: the provider form
              asks for both at once, and a generated one nobody copied would
              otherwise be gone the moment this screen replaced the form -
              recoverable only by rotating. The raw form's secret is the caller's
              own (the server does not echo it back), so the local state is the
              copy shown; `reveal_secret` covers a server-minted one. */}
          {(created.reveal_secret ?? secret) && (
            <SecretRevealField
              secret={created.reveal_secret ?? secret}
              label={t("secret")}
              note={t("createdSecretNote")}
              id="created-secret"
            />
          )}
          <DialogFooter>
            <Button onClick={() => onOpenChange(false)}>{t("done")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  const scheduleFields = type === "schedule" && (
    <ScheduleFields
      scheduleKind={scheduleKind}
      onScheduleKind={onCadence(setScheduleKind)}
      intervalCount={intervalCount}
      onIntervalCount={onCadence(setIntervalCount)}
      intervalUnit={intervalUnit}
      onIntervalUnit={onCadence(setIntervalUnit)}
      cron={{
        freq: cronFreq,
        onFreq: onCadence(setCronFreq),
        time: cronTime,
        onTime: onCadence(setCronTime),
        everyDays: cronEveryDays,
        onEveryDays: onCadence(setCronEveryDays),
        weekdays: cronWeekdays,
        onToggleWeekday: onCadence(toggleWeekday),
        dayOfMonth: cronDayOfMonth,
        onDayOfMonth: onCadence(setCronDayOfMonth),
        advanced: cronAdvanced,
        onAdvanced: onCadence(setCronAdvanced),
      }}
    />
  );

  if (editing) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className={cn(DIALOG_SCROLL, DIALOG_FORM)}>
          <DialogHeader>
            <DialogTitle>
              {type === "event" ? t("editTitleEvent") : t("editTitleSchedule")}
            </DialogTitle>
            <DialogDescription>
              {type === "event" ? t("editDescriptionEvent") : t("editDescriptionSchedule")}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <NameField value={name} onChange={setName} />
            <PromptField value={prompt} onChange={setPrompt} />

            {scheduleFields}

            {trigger.trigger_type === "event" && trigger.webhook_url && (
              <WebhookField url={trigger.webhook_url} />
            )}

            {/* The filter is the one event field that is editable in place -
                narrowing "which deliveries fire" is a filter edit, not a new
                trigger. The source and secret stay fixed (the secret rotates
                below instead). */}
            {trigger.trigger_type === "event" &&
              trigger.event_source &&
              (() => {
                const filters = SOURCE_FILTERS[trigger.event_source];
                return filters ? (
                  <div className="grid gap-4 sm:grid-cols-2">
                    <FormField label={t(filters[0])} htmlFor="edit-filter-a">
                      <Input
                        id="edit-filter-a"
                        value={filterA}
                        onChange={(event) => setFilterA(event.target.value)}
                        placeholder={t("filterOptional")}
                      />
                    </FormField>
                    <FormField label={t(filters[1])} htmlFor="edit-filter-b">
                      <Input
                        id="edit-filter-b"
                        value={filterB}
                        onChange={(event) => setFilterB(event.target.value)}
                        placeholder={t("filterOptional")}
                      />
                    </FormField>
                  </div>
                ) : null;
              })()}

            {trigger.trigger_type === "event" && trigger.can_manage && (
              <RotateSecretSection triggerId={trigger.id} rotate={rotateSecret} />
            )}

            {namedEnvironments.length > 0 && (
              <EnvironmentField
                value={environmentId}
                onChange={setEnvironmentId}
                environments={namedEnvironments}
                defaultEnvironment={defaultEnvironment}
              />
            )}
          </div>

          <DialogFooter className="sm:justify-between">
            <Button
              variant="secondary"
              disabled={!trigger.is_active || runNow.isPending}
              onClick={() => runNow.mutate(trigger.id)}
            >
              {t("runNow")}
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("cancel")}
              </Button>
              <Button onClick={submit} disabled={!canSubmit}>
                {t("save")}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* A ceiling, not a height. The message step's editor asks for eighteen
          rows and so fills a page on its own; the configure step holds three
          fields, and `h-[90vh]` gave it the same page with six hundred pixels of
          white under the last caption and the Continue button pinned to the
          bottom of the screen (#1069). The grid rows still pin the header and the
          nav and give the body whatever is between. */}
      <DialogContent className={cn(DIALOG_FRAMED, DIALOG_BROAD)}>
        <DialogHeader className="border-foreground/10 border-b px-6 py-4">
          <DialogTitle className="text-base font-semibold">
            {type === "event" ? t("newEvent") : t("newSchedule")}
          </DialogTitle>
          <DialogDescription>{t("createDescription")}</DialogDescription>
          <WizardSteps steps={steps} current={step} />
        </DialogHeader>

        <div className="min-h-0 scrollbar-thin overflow-y-auto px-6 py-5">
          {step === "event" && (
            <EventFields
              eventSource={eventSource}
              onEventSource={setEventSource}
              secret={secret}
              onSecret={setSecret}
              filterA={filterA}
              onFilterA={setFilterA}
              filterB={filterB}
              onFilterB={setFilterB}
            />
          )}

          {step === "configure" && (
            <div className="space-y-4">
              {agentId === null && (
                <FormField label={t("agent")} htmlFor="trigger-agent">
                  <Select
                    value={effectiveAgentId ?? ""}
                    onValueChange={(next) => {
                      setPickedAgentId(next);
                      // A named environment belongs to one agent; carrying the
                      // previous agent's choice across would be refused on create.
                      setEnvironmentId(DEFAULT_ENV);
                    }}
                  >
                    <SelectTrigger id="trigger-agent">
                      <SelectValue placeholder={t("chooseAgent")} />
                    </SelectTrigger>
                    <SelectContent>
                      {runnable.map((agent) => (
                        <SelectItem key={agent.id} value={agent.id}>
                          <span className="flex items-center gap-2">
                            <AgentAvatar
                              agentId={agent.id}
                              name={agent.name}
                              hasAvatar={agent.has_avatar}
                              colorSlot={agent.avatar_color}
                              size="sm"
                            />
                            {agent.name}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormField>
              )}

              <NameField value={name} onChange={setName} />

              {namedEnvironments.length > 0 && (
                <EnvironmentField
                  value={environmentId}
                  onChange={setEnvironmentId}
                  environments={namedEnvironments}
                  defaultEnvironment={defaultEnvironment}
                />
              )}
            </div>
          )}

          {step === "message" && (
            <div className="space-y-4">
              <TriggerTemplatePicker
                triggerType={type}
                eventSource={type === "event" ? eventSource : undefined}
                selectedKey={templateKey}
                onPick={applyTemplate}
                onScratch={scratchTemplate}
              />

              {/* The step is the message's own, so the editor gets the room a
                  long prompt needs. */}
              <PromptField value={prompt} onChange={setPrompt} rows={18} />
            </div>
          )}

          {step === "schedule" && (
            <div className="space-y-4">
              <CadencePresets
                scheduleKind={scheduleKind}
                intervalUnit={intervalUnit}
                intervalCount={intervalCount}
                cronFreq={cronFreq}
                cronTime={cronTime}
                cronWeekdays={cronWeekdays}
                onApply={applyPreset}
              />
              {scheduleFields}
            </div>
          )}
        </div>

        <WizardNav
          backIsStep={!onFirstStep}
          backLabel={onFirstStep ? t("cancel") : t("back")}
          onBack={onFirstStep ? () => onOpenChange(false) : handleBack}
          nextLabel={isLastStep ? t("create") : t("continue")}
          onNext={handleNext}
          nextDisabled={!canAdvance}
          isLast={isLastStep}
          busy={pending}
          busyLabel={t("creating")}
        />
      </DialogContent>
    </Dialog>
  );
}

function NameField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const t = useTranslations("triggers");
  return (
    <FormField label={t("nameLabel")} htmlFor="trigger-name" description={t("nameHelp")}>
      <Input
        id="trigger-name"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t("namePlaceholder")}
        maxLength={120}
      />
    </FormField>
  );
}

function PromptField({
  value,
  onChange,
  rows = 6,
}: {
  value: string;
  onChange: (value: string) => void;
  /** The wizard's message step passes more - a prompt is often long. */
  rows?: number;
}) {
  const t = useTranslations("triggers");
  return (
    <div className="space-y-1.5">
      <Label htmlFor="trigger-prompt">{t("prompt")}</Label>
      <MarkdownEditor
        id="trigger-prompt"
        label={t("prompt")}
        value={value}
        onChange={onChange}
        placeholder={t("promptPlaceholder")}
        rows={rows}
        describedBy="trigger-prompt-desc"
      />
      <p id="trigger-prompt-desc" className="text-muted-foreground text-xs leading-relaxed">
        {t("promptHelp")}
      </p>
    </div>
  );
}

/** A quick cadence worth one click: an interval, or a cron shape and a time. */
type CadencePreset =
  | { key: string; kind: "interval"; unit: IntervalUnit; count: number }
  | { key: string; kind: "cron"; freq: "daily"; time: string }
  | { key: string; kind: "cron"; freq: "weekly"; time: string; weekdays: number[] };

/** The presets on the schedule step, mirroring the KB sync-source pills. */
const CADENCE_PRESETS: readonly CadencePreset[] = [
  { key: "presetEvery15m", kind: "interval", unit: "minutes", count: 15 },
  { key: "presetHourly", kind: "interval", unit: "hours", count: 1 },
  { key: "presetEvery6h", kind: "interval", unit: "hours", count: 6 },
  { key: "presetDaily9", kind: "cron", freq: "daily", time: "09:00" },
  {
    key: "presetWeekdays9",
    kind: "cron",
    freq: "weekly",
    time: "09:00",
    weekdays: [1, 2, 3, 4, 5],
  },
];

interface CadencePresetsProps {
  scheduleKind: ScheduleKind;
  intervalUnit: IntervalUnit;
  intervalCount: string;
  cronFreq: CronFrequency;
  cronTime: string;
  cronWeekdays: number[];
  onApply: (preset: CadencePreset) => void;
}

/**
 * One-click cadences above the full builder. A pill lights up while the
 * controls below still spell out what it set, so a preset is a shortcut into
 * the builder rather than a mode of its own - editing any control underneath
 * simply unlights it.
 */
function CadencePresets({
  scheduleKind,
  intervalUnit,
  intervalCount,
  cronFreq,
  cronTime,
  cronWeekdays,
  onApply,
}: CadencePresetsProps) {
  const t = useTranslations("triggers");

  function isActive(preset: CadencePreset): boolean {
    if (preset.kind === "interval") {
      return (
        scheduleKind === "interval" &&
        intervalUnit === preset.unit &&
        Number(intervalCount) === preset.count
      );
    }
    if (scheduleKind !== "cron" || cronFreq !== preset.freq || cronTime !== preset.time) {
      return false;
    }
    if (preset.freq === "weekly") {
      return [...cronWeekdays].sort((a, b) => a - b).join(",") === preset.weekdays.join(",");
    }
    return true;
  }

  return (
    <div className="space-y-2">
      {/* The label the rest of the form uses, not a faint uppercase one: this is
          the control the cadence is actually steered by, and at 11px uppercase
          mono it was the least legible text in the dialog (#1069). */}
      <Label>{t("presetsLabel")}</Label>
      <div className="flex flex-wrap gap-2">
        {CADENCE_PRESETS.map((preset) => {
          const active = isActive(preset);
          return (
            <button
              key={preset.key}
              type="button"
              aria-pressed={active}
              onClick={() => onApply(preset)}
              className={cn(
                "border-input inline-flex rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                active
                  ? "bg-foreground text-background border-foreground"
                  : "text-foreground hover:border-foreground/40 hover:bg-accent",
              )}
            >
              {t(preset.key)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Everything the "at a set time" builder needs, bundled so it passes as one prop. */
interface CronBuilderState {
  freq: CronFrequency;
  onFreq: (freq: CronFrequency) => void;
  time: string;
  onTime: (value: string) => void;
  everyDays: string;
  onEveryDays: (value: string) => void;
  weekdays: number[];
  onToggleWeekday: (value: number) => void;
  dayOfMonth: string;
  onDayOfMonth: (value: string) => void;
  advanced: string;
  onAdvanced: (value: string) => void;
}

interface ScheduleFieldsProps {
  scheduleKind: ScheduleKind;
  onScheduleKind: (kind: ScheduleKind) => void;
  intervalCount: string;
  onIntervalCount: (value: string) => void;
  intervalUnit: IntervalUnit;
  onIntervalUnit: (unit: IntervalUnit) => void;
  cron: CronBuilderState;
}

function ScheduleFields({
  scheduleKind,
  onScheduleKind,
  intervalCount,
  onIntervalCount,
  intervalUnit,
  onIntervalUnit,
  cron,
}: ScheduleFieldsProps) {
  const t = useTranslations("triggers");
  return (
    <div className="space-y-3">
      <Tabs value={scheduleKind} onValueChange={(next) => onScheduleKind(next as ScheduleKind)}>
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="interval">{t("kindInterval")}</TabsTrigger>
          <TabsTrigger value="cron">{t("kindCron")}</TabsTrigger>
        </TabsList>
      </Tabs>
      {scheduleKind === "interval" ? (
        <div className="space-y-1">
          <Label htmlFor="trigger-interval">{t("runEvery")}</Label>
          <div className="flex gap-2">
            <Input
              id="trigger-interval"
              type="text"
              inputMode="numeric"
              value={intervalCount}
              aria-invalid={!intervalCountValid(intervalCount)}
              onChange={(event) => onIntervalCount(event.target.value.replace(/\D/g, ""))}
              className="w-24"
            />
            <Select
              value={intervalUnit}
              onValueChange={(next) => onIntervalUnit(next as IntervalUnit)}
            >
              <SelectTrigger className="flex-1" aria-label={t("unit")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="minutes">{t("unitMinutes")}</SelectItem>
                <SelectItem value="hours">{t("unitHours")}</SelectItem>
                <SelectItem value="days">{t("unitDays")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {!intervalCountValid(intervalCount) && (
            <p className="text-destructive text-xs" role="alert">
              {t("runEveryInvalid", { max: INTERVAL_MAX })}
            </p>
          )}
        </div>
      ) : (
        <CronBuilder {...cron} />
      )}
    </div>
  );
}

/**
 * The "at a set time" builder: a repeat preset and a clock time, compiled to cron
 * by `composeCron` in the parent. A non-technical user picks "every day at 09:00"
 * rather than writing `0 9 * * *`; "Custom (cron)" still takes a raw expression for
 * anything the presets miss. A live summary states what the current choices mean.
 */
function CronBuilder({
  freq,
  onFreq,
  time,
  onTime,
  everyDays,
  onEveryDays,
  weekdays,
  onToggleWeekday,
  dayOfMonth,
  onDayOfMonth,
  advanced,
  onAdvanced,
}: CronBuilderState) {
  const t = useTranslations("triggers");
  return (
    <div className="space-y-3">
      <FormField label={t("repeat")} htmlFor="cron-frequency">
        <Select value={freq} onValueChange={(next) => onFreq(next as CronFrequency)}>
          <SelectTrigger id="cron-frequency">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CRON_FREQUENCIES.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {t(option.key)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>

      {freq === "advanced" ? (
        <FormField label={t("cronExpression")} htmlFor="cron-advanced" description={t("cronHelp")}>
          <Input
            id="cron-advanced"
            value={advanced}
            onChange={(event) => onAdvanced(event.target.value)}
            placeholder="0 9 * * *"
            className="font-mono"
          />
        </FormField>
      ) : (
        <>
          {freq === "everyNDays" && (
            <div className="space-y-1">
              <Label htmlFor="cron-every-days">{t("runEvery")}</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="cron-every-days"
                  type="number"
                  min={1}
                  max={31}
                  value={everyDays}
                  onChange={(event) => onEveryDays(event.target.value)}
                  className="w-24"
                />
                <span className="text-muted-foreground text-sm">{t("unitDays")}</span>
              </div>
            </div>
          )}

          {freq === "weekly" && (
            <div className="space-y-1">
              <Label>{t("weekdaysLabel")}</Label>
              <div className="flex flex-wrap gap-1" role="group" aria-label={t("weekdaysLabel")}>
                {WEEKDAYS.map((day) => {
                  const active = weekdays.includes(day.value);
                  return (
                    <button
                      key={day.value}
                      type="button"
                      aria-pressed={active}
                      onClick={() => onToggleWeekday(day.value)}
                      className={cn(
                        // The same pill the quick presets wear, so the two rows
                        // of toggles in this dialog read as one control family.
                        "border-foreground/15 flex-1 rounded-full border px-2 py-1.5 font-mono text-[11px] tracking-wider uppercase transition-colors",
                        active
                          ? "bg-foreground text-background border-foreground"
                          : "text-foreground/65 hover:text-foreground hover:border-foreground/40",
                      )}
                    >
                      {t(day.key)}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {freq === "monthly" && (
            <FormField label={t("dayOfMonthLabel")} htmlFor="cron-day-of-month">
              <Input
                id="cron-day-of-month"
                type="number"
                min={1}
                max={31}
                value={dayOfMonth}
                onChange={(event) => onDayOfMonth(event.target.value)}
                className="w-24"
              />
            </FormField>
          )}

          {/* An "every N days" cadence is a continuous interval with no time of
              day to anchor to, so it offers no time field. */}
          {freq !== "everyNDays" && (
            <FormField label={t("timeLabel")} htmlFor="cron-time">
              <Input
                id="cron-time"
                type="time"
                value={time}
                onChange={(event) => onTime(event.target.value)}
                className="w-36"
              />
            </FormField>
          )}

          <p className="text-muted-foreground text-sm">
            <CronSummary
              freq={freq}
              time={time}
              everyDays={everyDays}
              weekdays={weekdays}
              dayOfMonth={dayOfMonth}
            />
          </p>
        </>
      )}
    </div>
  );
}

/** A plain-language restatement of the builder's current choices, for reassurance. */
function CronSummary({
  freq,
  time,
  everyDays,
  weekdays,
  dayOfMonth,
}: {
  freq: CronFrequency;
  time: string;
  everyDays: string;
  weekdays: number[];
  dayOfMonth: string;
}) {
  const t = useTranslations("triggers");
  if (freq === "everyNDays") {
    return <>{t("summaryEveryNDays", { count: clampInt(everyDays, 1, 31, 1) })}</>;
  }
  if (freq === "weekly") {
    const chosen = weekdays.length ? weekdays : [1];
    const days = [...chosen]
      .sort((a, b) => a - b)
      .map((value) => t(weekdayKey(value)))
      .join(", ");
    return <>{t("summaryWeekly", { time, days })}</>;
  }
  if (freq === "monthly") {
    return <>{t("summaryMonthly", { day: clampInt(dayOfMonth, 1, 31, 1), time })}</>;
  }
  return <>{t("summaryDaily", { time })}</>;
}

interface EventFieldsProps {
  eventSource: EventSource;
  onEventSource: (source: EventSource) => void;
  secret: string;
  onSecret: (value: string) => void;
  filterA: string;
  onFilterA: (value: string) => void;
  filterB: string;
  onFilterB: (value: string) => void;
}

// Which two optional substring filters each source offers, by translation key,
// or none. Kept beside the backend's per-source config so the form only asks for
// filters the server will actually apply.
const SOURCE_FILTERS: Partial<Record<EventSource, readonly [string, string]>> = {
  gmail: ["subjectContains", "senderContains"],
};

/** The sources the picker offers, each with its static label key so the catalog
 *  check can see them; the mark beside each comes from `EventSourceMark`. */
const EVENT_SOURCES: readonly { value: EventSource; labelKey: string }[] = [
  { value: "github", labelKey: "sourceGithub" },
  { value: "webhook", labelKey: "sourceWebhook" },
];

/** Where each source's delivery comes from - a static key per source so the
 *  catalog check can see them, rather than one interpolated key it cannot. */
function sourceHelp(t: ReturnType<typeof useTranslations>, source: EventSource): string {
  switch (source) {
    case "github":
      return t("sourceHelpGithub");
    case "gmail":
      return t("sourceHelpGmail");
    case "webhook":
      return t("sourceHelpWebhook");
  }
}

function EventFields({
  eventSource,
  onEventSource,
  secret,
  onSecret,
  filterA,
  onFilterA,
  filterB,
  onFilterB,
}: EventFieldsProps) {
  const t = useTranslations("triggers");
  const filters = SOURCE_FILTERS[eventSource];
  return (
    <div className="space-y-3">
      <FormField
        label={t("eventSource")}
        htmlFor="trigger-source"
        description={sourceHelp(t, eventSource)}
      >
        <Select value={eventSource} onValueChange={(next) => onEventSource(next as EventSource)}>
          <SelectTrigger id="trigger-source">
            {/* Radix mirrors the chosen item's content, mark and all, into the value. */}
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {EVENT_SOURCES.map((source) => (
              <SelectItem key={source.value} value={source.value}>
                <span className="flex items-center gap-2">
                  <EventSourceMark source={source.value} className="h-4 w-4 shrink-0" />
                  {t(source.labelKey)}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      {/* The delivery URL is shown before the secret, greyed and with the id it
          only gets on save, so the reader sees what the secret is *for* rather
          than being asked for a password to a mechanism nothing has named yet -
          and in the order they will use them, URL to paste first. The full URL,
          built on the API host from PUBLIC_BASE_URL, appears once the trigger
          exists (`WebhookField`). */}
      <div className="space-y-1">
        <p className="text-sm font-medium">{t("webhookUrlPreview")}</p>
        <p className="text-muted-foreground bg-muted/40 rounded-md border px-3 py-2 font-mono text-xs break-all">
          {t("webhookUrlPreviewValue", { source: eventSource })}
        </p>
        <p className="text-muted-foreground text-xs">{t("webhookUrlPreviewHelp")}</p>
      </div>
      <div className="space-y-1">
        <Label htmlFor="trigger-secret">{t("secret")}</Label>
        <div className="flex gap-2">
          <Input
            id="trigger-secret"
            value={secret}
            onChange={(event) => onSecret(event.target.value)}
            placeholder={t("secretPlaceholder")}
            className="flex-1 font-mono"
          />
          <Button type="button" variant="outline" onClick={() => onSecret(generateSecret())}>
            {t("generate")}
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">{t("secretHelp")}</p>
      </div>
      {filters && (
        <>
          <FormField label={t(filters[0])} htmlFor="trigger-filter-a">
            <Input
              id="trigger-filter-a"
              value={filterA}
              onChange={(event) => onFilterA(event.target.value)}
              placeholder={t("filterOptional")}
            />
          </FormField>
          <FormField label={t(filters[1])} htmlFor="trigger-filter-b">
            <Input
              id="trigger-filter-b"
              value={filterB}
              onChange={(event) => onFilterB(event.target.value)}
              placeholder={t("filterOptional")}
            />
          </FormField>
        </>
      )}
    </div>
  );
}

/**
 * Rotating an event trigger's signing secret, on its edit surface.
 *
 * The secret authenticates each webhook delivery; rotating mints a new one and the
 * old one stops working at once. What the caller must then do depends on delivery:
 * a manual trigger returns the new secret to paste into the provider (shown once,
 * never on a read), while an auto-webhook trigger is re-registered by the platform
 * with nothing left to paste. Only offered on a row the caller may manage.
 */
function RotateSecretSection({
  triggerId,
  rotate,
}: {
  triggerId: string;
  rotate: ReturnType<typeof useTriggers>["rotateSecret"];
}) {
  const t = useTranslations("triggers");
  const [rotated, setRotated] = useState<TriggerCreated | null>(null);

  async function onRotate() {
    try {
      setRotated(await rotate.mutateAsync(triggerId));
    } catch {
      // The hook toasts the server's refusal; leave the button to try again.
    }
  }

  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="space-y-0.5">
        <p className="text-sm font-medium">{t("rotateSecretTitle")}</p>
        <p className="text-muted-foreground text-xs">{t("rotateSecretHelp")}</p>
      </div>
      {rotated === null ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={rotate.isPending}
          onClick={onRotate}
        >
          {t("rotateSecret")}
        </Button>
      ) : rotated.reveal_secret ? (
        <SecretRevealField
          secret={rotated.reveal_secret}
          label={t("secret")}
          note={t("rotateRevealNote")}
          id="rotated-secret"
        />
      ) : (
        <p className="text-muted-foreground text-xs">{t("rotateAutoNote")}</p>
      )}
    </div>
  );
}

function WebhookField({ url }: { url: string }) {
  const t = useTranslations("triggers");
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(url);
    setCopied(true);
  }

  return (
    <div className="space-y-1">
      <Label htmlFor="trigger-webhook">{t("webhookUrl")}</Label>
      <div className="flex gap-2">
        <Input id="trigger-webhook" value={url} readOnly className="flex-1 font-mono text-xs" />
        <Button type="button" variant="outline" onClick={copy}>
          {copied ? t("copied") : t("copy")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("webhookHelp")}</p>
    </div>
  );
}
