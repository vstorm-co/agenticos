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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import { useAgentEnvironments, useAgents } from "@/hooks";
import { useTriggers } from "@/hooks/use-triggers";
import { useAgentSelectionStore } from "@/stores";
import { type IntervalUnit, intervalToUnit, unitToSeconds } from "@/lib/trigger-format";
import type {
  EventSource,
  ScheduleKind,
  Trigger,
  TriggerCreate,
  TriggerType,
  TriggerUpdate,
} from "@/types/triggers";

/** Sentinel for "the default environment" - a Select item may not be empty. */
const DEFAULT_ENV = "__default__";
const MAX_PROMPT = 10000;
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

  const { create, update, runNow } = useTriggers(effectiveAgentId);
  const { environments } = useAgentEnvironments(effectiveAgentId);
  const namedEnvironments = environments.filter((environment) => !environment.is_default);

  const [type, setType] = useState<TriggerType>(trigger?.trigger_type ?? initialType);
  const [prompt, setPrompt] = useState(trigger?.prompt ?? "");
  const [environmentId, setEnvironmentId] = useState(trigger?.environment_id ?? DEFAULT_ENV);

  const seed = trigger?.interval_seconds
    ? intervalToUnit(trigger.interval_seconds)
    : { unit: "minutes" as IntervalUnit, count: 15 };
  const [scheduleKind, setScheduleKind] = useState<ScheduleKind>(
    trigger?.schedule_kind ?? "interval",
  );
  const [intervalCount, setIntervalCount] = useState(String(seed.count));
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>(seed.unit);
  const [cron, setCron] = useState(trigger?.cron_expression ?? "0 9 * * *");

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

  function buildCreate(): TriggerCreate {
    const base = {
      prompt,
      trigger_type: type,
      environment_id: environmentId === DEFAULT_ENV ? null : environmentId,
    };
    if (type === "schedule") {
      return scheduleKind === "cron"
        ? { ...base, schedule_kind: "cron", cron_expression: cron.trim() }
        : {
            ...base,
            schedule_kind: "interval",
            interval_seconds: unitToSeconds(intervalUnit, Math.max(1, Number(intervalCount) || 1)),
          };
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
        const env = environmentId === DEFAULT_ENV ? null : environmentId;
        if (env !== (trigger.environment_id ?? null)) patch.environment_id = env;
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

  const shapeValid = editing
    ? true
    : type === "schedule"
      ? scheduleKind === "cron"
        ? cron.trim().length > 0
        : Number(intervalCount) > 0
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
          {!editing && (
            <Tabs value={type} onValueChange={(next) => setType(next as TriggerType)}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="schedule">{t("typeSchedule")}</TabsTrigger>
                <TabsTrigger value="event">{t("typeEvent")}</TabsTrigger>
              </TabsList>
            </Tabs>
          )}

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

          <FormField label={t("prompt")} htmlFor="trigger-prompt" description={t("promptHelp")}>
            <Textarea
              id="trigger-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t("promptPlaceholder")}
              maxLength={MAX_PROMPT}
              rows={3}
            />
          </FormField>

          {!editing && type === "schedule" && (
            <ScheduleFields
              scheduleKind={scheduleKind}
              onScheduleKind={setScheduleKind}
              intervalCount={intervalCount}
              onIntervalCount={setIntervalCount}
              intervalUnit={intervalUnit}
              onIntervalUnit={setIntervalUnit}
              cron={cron}
              onCron={setCron}
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

interface ScheduleFieldsProps {
  scheduleKind: ScheduleKind;
  onScheduleKind: (kind: ScheduleKind) => void;
  intervalCount: string;
  onIntervalCount: (value: string) => void;
  intervalUnit: IntervalUnit;
  onIntervalUnit: (unit: IntervalUnit) => void;
  cron: string;
  onCron: (value: string) => void;
}

function ScheduleFields({
  scheduleKind,
  onScheduleKind,
  intervalCount,
  onIntervalCount,
  intervalUnit,
  onIntervalUnit,
  cron,
  onCron,
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
        <FormField label={t("cronExpression")} htmlFor="trigger-cron" description={t("cronHelp")}>
          <Input
            id="trigger-cron"
            value={cron}
            onChange={(event) => onCron(event.target.value)}
            placeholder="0 9 * * *"
            className="font-mono"
          />
        </FormField>
      )}
    </div>
  );
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
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="github">{t("sourceGithub")}</SelectItem>
            <SelectItem value="email">{t("sourceEmail")}</SelectItem>
            <SelectItem value="linkedin">{t("sourceLinkedin")}</SelectItem>
            <SelectItem value="webhook">{t("sourceWebhook")}</SelectItem>
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
