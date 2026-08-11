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
  const [subjectContains, setSubjectContains] = useState("");
  const [senderContains, setSenderContains] = useState("");

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
    const config: Record<string, string> = {};
    if (eventSource === "email" && subjectContains.trim())
      config.subject_contains = subjectContains.trim();
    if (eventSource === "email" && senderContains.trim())
      config.sender_contains = senderContains.trim();
    return {
      ...base,
      event_source: eventSource,
      event_secret: secret,
      event_config: Object.keys(config).length ? config : undefined,
    };
  }

  async function submit() {
    try {
      if (editing) {
        await update.mutateAsync({
          triggerId: trigger.id,
          patch: { prompt, environment_id: environmentId === DEFAULT_ENV ? null : environmentId },
        });
      } else {
        await create.mutateAsync(buildCreate());
      }
      onOpenChange(false);
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
              subjectContains={subjectContains}
              onSubjectContains={setSubjectContains}
              senderContains={senderContains}
              onSenderContains={setSenderContains}
            />
          )}

          {editing && trigger.trigger_type === "event" && trigger.webhook_path && (
            <WebhookField path={trigger.webhook_path} />
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
  subjectContains: string;
  onSubjectContains: (value: string) => void;
  senderContains: string;
  onSenderContains: (value: string) => void;
}

function EventFields({
  eventSource,
  onEventSource,
  secret,
  onSecret,
  subjectContains,
  onSubjectContains,
  senderContains,
  onSenderContains,
}: EventFieldsProps) {
  const t = useTranslations("triggers");
  return (
    <div className="space-y-3">
      <FormField label={t("eventSource")} htmlFor="trigger-source">
        <Select value={eventSource} onValueChange={(next) => onEventSource(next as EventSource)}>
          <SelectTrigger id="trigger-source">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="github">{t("sourceGithub")}</SelectItem>
            <SelectItem value="email">{t("sourceEmail")}</SelectItem>
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
      {eventSource === "email" && (
        <>
          <FormField label={t("subjectContains")} htmlFor="trigger-subject">
            <Input
              id="trigger-subject"
              value={subjectContains}
              onChange={(event) => onSubjectContains(event.target.value)}
              placeholder={t("filterOptional")}
            />
          </FormField>
          <FormField label={t("senderContains")} htmlFor="trigger-sender">
            <Input
              id="trigger-sender"
              value={senderContains}
              onChange={(event) => onSenderContains(event.target.value)}
              placeholder={t("filterOptional")}
            />
          </FormField>
        </>
      )}
    </div>
  );
}

function WebhookField({ path }: { path: string }) {
  const t = useTranslations("triggers");
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return (
    <FormField label={t("webhookUrl")} htmlFor="trigger-webhook" description={t("webhookHelp")}>
      <Input
        id="trigger-webhook"
        value={`${origin}${path}`}
        readOnly
        className="font-mono text-xs"
      />
    </FormField>
  );
}
