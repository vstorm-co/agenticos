"use client";

import { useState } from "react";
import { Pause, Play, Plus, Trash2 } from "lucide-react";

import { LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgentEnvironments, useExposures } from "@/hooks";
import type { ExposureSurface, SessionScope } from "@/types/exposures";
import { useTranslations } from "next-intl";

interface ExposuresPanelProps {
  agentId: string;
  /**
   * Where an agent is available is the same class of decision as what it runs,
   * so the server demands `agents:publish` on this agent. The caller passes the
   * answer in rather than this panel re-deriving it, for the same reason the
   * sharing panel does.
   */
  canManage: boolean;
  /**
   * Whether the agent keeps files at all.
   *
   * Decides only whether the sharing override is offered. Read from the spec by
   * the page rather than re-derived here: this panel is about *where* an agent
   * is available, and reaching into the capability list for one control would
   * make it a second reader of the spec's shape.
   */
  hasWorkspace: boolean;
}

const SURFACE_LABEL: Record<ExposureSurface, string> = {
  slack: "Slack",
  telegram: "Telegram",
  mattermost: "Mattermost",
};

/**
 * Where one agent is available.
 *
 * One section for every surface, not one per channel: an exposure is a single
 * concept, and splitting the UI by platform would be the first step towards
 * splitting the model by platform too.
 *
 * The empty state says what the absence means. An agent with no bindings is not
 * misconfigured - it is reachable from the dashboard and the API and nowhere
 * else, which is the default, and a bot that has stopped answering a handle it
 * used to answer is explained here rather than in a changelog.
 */
/** Sentinel for "the default environment" - a Select item may not be empty. */
const DEFAULT_ENV = "__default__";

/** The same trick for "whatever the spec says". */
const SPEC_SCOPE = "__spec__";

/**
 * Who shares a workspace *here*, when this surface disagrees with the spec.
 *
 * The labels are the surface's own vocabulary rather than the Builder's, because
 * this is where the question stops being abstract: on Slack a thread is a chat,
 * so "this conversation" means per-thread and a busy channel is fifty
 * workspaces. That is exactly the mistake this control exists to let somebody
 * fix without republishing the agent.
 */
const SCOPE_LABEL: Record<SessionScope, string> = {
  run: "fresh each turn",
  conversation: "per chat or thread",
  channel: "per channel",
  user: "per person",
  agent: "one for everyone",
};

export function ExposuresPanel({ agentId, canManage, hasWorkspace }: ExposuresPanelProps) {
  const t = useTranslations("agents");
  const {
    exposures,
    isLoading,
    available,
    expose,
    setActive,
    setEnvironment,
    setSessionScope,
    revoke,
  } = useExposures(agentId);
  const { environments } = useAgentEnvironments(agentId);
  const [selectedBotId, setSelectedBotId] = useState("");
  // Only worth a control when there is a choice: with the default alone, every
  // binding serves it and a picker would offer one option.
  const namedEnvironments = environments.filter((environment) => !environment.is_default);

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={2} />;

  function addExposure() {
    expose.mutate(selectedBotId);
    setSelectedBotId("");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("whereAgentAvailable")}</CardTitle>
        <CardDescription>
          A published agent answers in the dashboard and through the API. To reach it from a chat
          platform, add the bot here - an agent is mentionable by <code>@handle</code> only on the
          bots it is bound to.
          {hasWorkspace && (
            <>
              {" "}
              A tool that asks for approval parks the run until somebody answers in this dashboard,
              so on a chat platform the thread sits there meanwhile - which reads as the bot being
              broken. For an agent people reach from a channel, the workable setting is a shell that
              is not gated, inside a container with no network.
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {exposures.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("notAvailableAnyChannel")}</p>
        )}

        {exposures.map((exposure) => (
          <div key={exposure.id} className="space-y-3 rounded-md border p-3">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {SURFACE_LABEL[exposure.surface]} - {exposure.channel_bot_name}
                </p>
                {!exposure.is_active && (
                  <p className="text-muted-foreground text-xs">{t("pausedHandleAnswersNothing")}</p>
                )}
              </div>
              {namedEnvironments.length > 0 && (
                <Select
                  value={exposure.environment_id ?? DEFAULT_ENV}
                  disabled={!canManage || setEnvironment.isPending}
                  onValueChange={(next) =>
                    setEnvironment.mutate({
                      exposureId: exposure.id,
                      environmentId: next === DEFAULT_ENV ? null : next,
                    })
                  }
                >
                  <SelectTrigger
                    className="w-36"
                    aria-label={`Environment on ${exposure.channel_bot_name}`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT_ENV}>{t("default3")}</SelectItem>
                    {namedEnvironments.map((environment) => (
                      <SelectItem key={environment.id} value={environment.id}>
                        {environment.name} (v{environment.version})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {/* Only where the agent has a workspace at all: an override on an
                  agent that keeps no files is a control that changes nothing,
                  and a section full of those is how the real ones get ignored. */}
              {hasWorkspace && (
                <Select
                  value={exposure.session_scope ?? SPEC_SCOPE}
                  disabled={!canManage || setSessionScope.isPending}
                  onValueChange={(next) =>
                    setSessionScope.mutate({
                      exposureId: exposure.id,
                      sessionScope: next === SPEC_SCOPE ? null : (next as SessionScope),
                    })
                  }
                >
                  <SelectTrigger
                    className="w-44"
                    aria-label={`Workspace sharing on ${exposure.channel_bot_name}`}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={SPEC_SCOPE}>{t("asAgentSays")}</SelectItem>
                    {(Object.keys(SCOPE_LABEL) as SessionScope[]).map((scope) => (
                      <SelectItem key={scope} value={scope}>
                        {SCOPE_LABEL[scope]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Button
                variant="ghost"
                size="sm"
                disabled={!canManage || setActive.isPending}
                aria-label={
                  exposure.is_active
                    ? `Pause on ${exposure.channel_bot_name}`
                    : `Resume on ${exposure.channel_bot_name}`
                }
                onClick={() =>
                  setActive.mutate({ exposureId: exposure.id, isActive: !exposure.is_active })
                }
              >
                {exposure.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={!canManage || revoke.isPending}
                aria-label={`Remove from ${exposure.channel_bot_name}`}
                onClick={() => revoke.mutate(exposure.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}

        {canManage &&
          (available.length > 0 ? (
            <div className="flex items-end gap-3 border-t pt-3">
              <div className="flex-1 space-y-1">
                <Label htmlFor="exposure-bot">{t("addChannel")}</Label>
                <Select value={selectedBotId} onValueChange={setSelectedBotId}>
                  <SelectTrigger id="exposure-bot">
                    <SelectValue placeholder={t("chooseBot")} />
                  </SelectTrigger>
                  <SelectContent>
                    {available.map((target) => (
                      <SelectItem key={target.id} value={target.id}>
                        {SURFACE_LABEL[target.platform]} - {target.name}
                        {!target.is_active && " (inactive)"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button disabled={!selectedBotId || expose.isPending} onClick={addExposure}>
                <Plus className="mr-2 h-4 w-4" />
                {t("add2")}
              </Button>
            </div>
          ) : (
            // A disabled picker here was a dead end: it said no bot could be
            // chosen without saying which of the two absences this is - no
            // bots at all, or all of them already bound.
            <p className="text-muted-foreground border-t pt-3 text-sm">
              {exposures.length > 0 ? t("agentAlreadyEveryBot") : t("organizationHasNoChannel")}
            </p>
          ))}
      </CardContent>
    </Card>
  );
}
