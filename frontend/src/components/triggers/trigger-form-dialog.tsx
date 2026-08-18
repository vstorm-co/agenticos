"use client";

import { useState } from "react";
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
} from "@/components/ui";
import { EventSourceMark } from "@/components/triggers/event-source-mark";
import { ScheduleTemplatePicker } from "@/components/triggers/schedule-template-picker";
import { SecretRevealField } from "@/components/triggers/secret-reveal-field";
import { useAgentEnvironments, useAgents } from "@/hooks";
import { useTriggers } from "@/hooks/use-triggers";
import { useAgentSelectionStore } from "@/stores";
import { type IntervalUnit, intervalToUnit, unitToSeconds } from "@/lib/trigger-format";
import type {
  EventSource,
  ScheduleKind,
  Trigger,
  TriggerCreate,
  TriggerCreated,
  TriggerType,
  TriggerUpdate,
} from "@/types/triggers";
import type { ScheduleTemplate } from "@/types/schedule-templates";

/** Sentinel for "the default environment" - a Select item may not be empty. */
const DEFAULT_ENV = "__default__";
/** The backend's floor for a webhook secret; the generator comfortably clears it. */
const MIN_SECRET = 16;

/** A strong random signing secret, so nobody has to invent one. */
function generateSecret(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The two config keys each source's filters map onto, or none. */
const FILTER_KEYS: Partial<Record<EventSource, readonly [string, string]>> = {
  email: ["subject_contains", "sender_contains"],
  linkedin: ["author_contains", "text_contains"],
};

/**
 * The `event_config` a source's two substring filters produce, or undefined when
 * the source takes none (GitHub fires on its default action, the generic webhook
 * on any signed delivery). Only non-empty filters are sent, so the server stores
 * exactly what narrows the trigger and nothing that means "match anything".
 */
function eventFilterConfig(
  source: EventSource,
  filterA: string,
  filterB: string,
): Record<string, string> | undefined {
  const keys = FILTER_KEYS[source];
  if (!keys) return undefined;
  const config: Record<string, string> = {};
  if (filterA) config[keys[0]] = filterA;
  if (filterB) config[keys[1]] = filterB;
  return Object.keys(config).length ? config : undefined;
}

/**
 * How the "at a set time" builder repeats, before it is compiled to cron. Each
 * maps to a crontab shape: daily `M H * * *`, every-N-days `M H * / N * *`, weekly
 * `M H * * <days>`, monthly `M H <dom> * *`. `advanced` is the escape hatch that
 * takes a raw expression for the cases the presets do not cover.
 */
type CronFrequency = "daily" | "everyNDays" | "weekly" | "monthly" | "advanced";

/** The repeat options, as translation keys so the catalog check can see them. */
const CRON_FREQUENCIES: readonly { value: CronFrequency; key: string }[] = [
  { value: "daily", key: "freqDaily" },
  { value: "everyNDays", key: "freqEveryNDays" },
  { value: "weekly", key: "freqWeekly" },
  { value: "monthly", key: "freqMonthly" },
  { value: "advanced", key: "freqAdvanced" },
];

/** The weekdays, in cron's numbering (0 = Sunday), Monday-first for display. */
const WEEKDAYS: readonly { value: number; key: string }[] = [
  { value: 1, key: "weekdayMon" },
  { value: 2, key: "weekdayTue" },
  { value: 3, key: "weekdayWed" },
  { value: 4, key: "weekdayThu" },
  { value: 5, key: "weekdayFri" },
  { value: 6, key: "weekdaySat" },
  { value: 0, key: "weekdaySun" },
];

/** The translation key for a weekday value, defaulting to Monday off-range. */
function weekdayKey(value: number): string {
  return WEEKDAYS.find((day) => day.value === value)?.key ?? "weekdayMon";
}

/** A bounded integer from a form string, or the fallback when it is not one. */
function clampInt(value: string, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

/** The builder state a cron expression seeds, for editing an existing schedule. */
interface ParsedCron {
  freq: CronFrequency;
  time: string;
  everyDays: string;
  weekdays: number[];
  dayOfMonth: string;
}

/**
 * A cron expression read back into the builder's choices, or "advanced" when no
 * preset represents it. Only the shapes `composeCron` produces are recognised - a
 * fixed minute and hour, a wildcard month, and one of daily / every-N-days /
 * weekdays / day-of-month - so a builder-made schedule round-trips on edit, and a
 * hand-written one opens on its raw expression rather than a wrong preset.
 */
function parseCron(expression: string): ParsedCron {
  const fallback: ParsedCron = {
    freq: "advanced",
    time: "09:00",
    everyDays: "2",
    weekdays: [1],
    dayOfMonth: "1",
  };
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) return fallback;
  const [rawMinute, rawHour, dom, month, dow] = parts as [string, string, string, string, string];
  const minute = Number(rawMinute);
  const hour = Number(rawHour);
  const timed =
    Number.isInteger(minute) &&
    minute >= 0 &&
    minute <= 59 &&
    Number.isInteger(hour) &&
    hour >= 0 &&
    hour <= 23;
  if (!timed || month !== "*") return fallback;
  const time = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  if (dom === "*" && dow === "*") return { ...fallback, freq: "daily", time };
  const everyN = /^\*\/([0-9]+)$/.exec(dom)?.[1];
  if (everyN !== undefined && dow === "*") {
    return { ...fallback, freq: "everyNDays", time, everyDays: everyN };
  }
  if (dom === "*" && dow !== "*") {
    const days = dow.split(",").map(Number);
    if (days.every((day) => Number.isInteger(day) && day >= 0 && day <= 6)) {
      return { ...fallback, freq: "weekly", time, weekdays: days };
    }
    return fallback;
  }
  const day = Number(dom);
  if (dow === "*" && Number.isInteger(day) && day >= 1 && day <= 31) {
    return { ...fallback, freq: "monthly", time, dayOfMonth: String(day) };
  }
  return fallback;
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
  const runnable = agents.filter((agent) => agent.status === "published");
  const [pickedAgentId, setPickedAgentId] = useState("");
  // The user's starred default, or the first published agent, the moment the
  // list arrives - the same resolution the chat's own picker makes.
  const seededAgentId =
    pickedAgentId || (runnable.find((agent) => agent.id === defaultAgentId) ?? runnable[0])?.id;
  const effectiveAgentId = agentId ?? seededAgentId ?? null;

  const { create, update, runNow, rotateSecret } = useTriggers(effectiveAgentId);
  const { environments } = useAgentEnvironments(effectiveAgentId);
  const namedEnvironments = environments.filter((environment) => !environment.is_default);

  // A trigger's kind is fixed once the dialog opens: editing keeps the row's type,
  // and creating takes whichever kind the entry point chose - "New schedule" opens
  // this on a schedule, the portal grid's "Advanced: custom webhook" hatch on an
  // event. There is no in-dialog switch, because event triggers are created from
  // the portal grid by default, not this raw form.
  const type = trigger?.trigger_type ?? initialType;
  const [prompt, setPrompt] = useState(trigger?.prompt ?? "");
  const [name, setName] = useState(trigger?.name ?? "");
  const [environmentId, setEnvironmentId] = useState(trigger?.environment_id ?? DEFAULT_ENV);

  const seed = trigger?.interval_seconds
    ? intervalToUnit(trigger.interval_seconds)
    : { unit: "minutes" as IntervalUnit, count: 15 };
  const [scheduleKind, setScheduleKind] = useState<ScheduleKind>(
    trigger?.schedule_kind ?? "interval",
  );
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

  const [eventSource, setEventSource] = useState<EventSource>(trigger?.event_source ?? "github");
  const [secret, setSecret] = useState("");
  // Two generic substring filters; what they mean is the source's business - a
  // subject and sender for email, an author and text for LinkedIn - so the keys
  // are mapped in `buildCreate` and the labels in `EventFields`.
  const [filterA, setFilterA] = useState("");
  const [filterB, setFilterB] = useState("");
  // The event trigger just created, held so the dialog can show its webhook URL
  // to paste into the provider before it closes - the one thing an event trigger
  // needs that a schedule does not.
  const [created, setCreated] = useState<Trigger | null>(null);

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

  /** Prefill the prompt and cadence from a seeded template, still editable below. */
  function applyTemplate(template: ScheduleTemplate) {
    setTemplateKey(template.key);
    setPrompt(template.prompt);
    setCadenceTouched(true);
    const cadence = template.suggested_cadence;
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
      interval_seconds: unitToSeconds(intervalUnit, Math.max(1, Number(intervalCount) || 1)),
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
      event_config: eventFilterConfig(eventSource, filterA.trim(), filterB.trim()),
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
  const scheduleValid = scheduleKind === "cron" ? cronValid : Number(intervalCount) > 0;
  // Editing a schedule can now change its cadence, so the cadence is guarded then
  // too; an event edit has no cadence and only its prompt/name to check.
  const shapeValid = editing
    ? type !== "schedule" || scheduleValid
    : type === "schedule"
      ? scheduleValid
      : secret.length >= MIN_SECRET;
  const canSubmit = prompt.trim().length > 0 && shapeValid && effectiveAgentId !== null && !pending;

  if (created !== null) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("createdTitle")}</DialogTitle>
            <DialogDescription>{t("createdDescription")}</DialogDescription>
          </DialogHeader>
          {created.webhook_url && <WebhookField url={created.webhook_url} />}
          <DialogFooter>
            <Button onClick={() => onOpenChange(false)}>{t("done")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {editing ? t("editTitle") : type === "event" ? t("newEvent") : t("newSchedule")}
          </DialogTitle>
          <DialogDescription>
            {editing ? t("editDescription") : t("createDescription")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {agentId === null && !editing && (
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
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}

          {!editing && type === "schedule" && (
            <ScheduleTemplatePicker
              selectedKey={templateKey}
              onPick={applyTemplate}
              onScratch={scratchTemplate}
            />
          )}

          <div className="space-y-1.5">
            <Label htmlFor="trigger-prompt">{t("prompt")}</Label>
            <MarkdownEditor
              id="trigger-prompt"
              label={t("prompt")}
              value={prompt}
              onChange={setPrompt}
              placeholder={t("promptPlaceholder")}
              rows={6}
              describedBy="trigger-prompt-desc"
            />
            <p id="trigger-prompt-desc" className="text-muted-foreground text-xs leading-relaxed">
              {t("promptHelp")}
            </p>
          </div>

          <FormField label={t("nameLabel")} htmlFor="trigger-name" description={t("nameHelp")}>
            <Input
              id="trigger-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("namePlaceholder")}
              maxLength={120}
            />
          </FormField>

          {type === "schedule" && (
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
          )}

          {!editing && type === "event" && (
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

          {editing && trigger.trigger_type === "event" && trigger.webhook_url && (
            <WebhookField url={trigger.webhook_url} />
          )}

          {editing && trigger.trigger_type === "event" && trigger.can_manage && (
            <RotateSecretSection triggerId={trigger.id} rotate={rotateSecret} />
          )}

          {namedEnvironments.length > 0 && (
            <FormField label={t("environment")} htmlFor="trigger-environment">
              <Select value={environmentId} onValueChange={setEnvironmentId}>
                <SelectTrigger id="trigger-environment">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_ENV}>{t("defaultEnvironment")}</SelectItem>
                  {namedEnvironments.map((environment) => (
                    <SelectItem key={environment.id} value={environment.id}>
                      {environment.name} (v{environment.version})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
        </div>

        <DialogFooter className={editing ? "sm:justify-between" : undefined}>
          {editing && (
            <Button
              variant="secondary"
              disabled={!trigger.is_active || runNow.isPending}
              onClick={() => runNow.mutate(trigger.id)}
            >
              {t("runNow")}
            </Button>
          )}
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={submit} disabled={!canSubmit}>
              {editing ? t("save") : t("create")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
              type="number"
              min={1}
              value={intervalCount}
              onChange={(event) => onIntervalCount(event.target.value)}
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
                    <Button
                      key={day.value}
                      type="button"
                      variant={active ? "default" : "outline"}
                      aria-pressed={active}
                      onClick={() => onToggleWeekday(day.value)}
                      className="h-8 flex-1 px-2 text-xs"
                    >
                      {t(day.key)}
                    </Button>
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
  email: ["subjectContains", "senderContains"],
  linkedin: ["authorContains", "textContains"],
};

/** The sources the picker offers, each with its static label key so the catalog
 *  check can see them; the mark beside each comes from `EventSourceMark`. */
const EVENT_SOURCES: readonly { value: EventSource; labelKey: string }[] = [
  { value: "github", labelKey: "sourceGithub" },
  { value: "email", labelKey: "sourceEmail" },
  { value: "linkedin", labelKey: "sourceLinkedin" },
  { value: "webhook", labelKey: "sourceWebhook" },
];

/** Where each source's delivery comes from - a static key per source so the
 *  catalog check can see them, rather than one interpolated key it cannot. */
function sourceHelp(t: ReturnType<typeof useTranslations>, source: EventSource): string {
  switch (source) {
    case "github":
      return t("sourceHelpGithub");
    case "email":
      return t("sourceHelpEmail");
    case "linkedin":
      return t("sourceHelpLinkedin");
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
