"use client";

import { useState } from "react";
import { Pause, Play, Trash2 } from "lucide-react";

import { LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgentEnvironments, useChannelBots, useExposures, usePermissions } from "@/hooks";
import { AddChannelDialog } from "@/components/channels/add-channel-dialog";
import { ExposureChannelTiles, SURFACE_LABEL } from "@/components/agents/exposure-channel-tiles";
import { ExposurePrompt } from "@/components/agents/exposure-prompt";
import { ExposureCostReporting } from "@/components/agents/exposure-cost-reporting";
import { ExposureTools } from "@/components/agents/exposure-tools";
import type { ExposureSurface } from "@/types/exposures";
import { Perm } from "@/types/permissions";
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

export function ExposuresPanel({ agentId, canManage, hasWorkspace }: ExposuresPanelProps) {
  const t = useTranslations("agents");
  const {
    exposures,
    isLoading,
    available,
    expose,
    setActive,
    setEnvironment,
    setPrompt,
    setTools,
    setUsageReporting,
    revoke,
  } = useExposures(agentId);
  const { environments } = useAgentEnvironments(agentId);
  const { can } = usePermissions();
  const canRegister = can(Perm.channelsManage);
  // Only the mutation: the bot list is the exposure targets above, and reading
  // `/channels/bots` too would ask `channels:manage` of every publisher.
  const { create: createBot } = useChannelBots(false);
  const [registering, setRegistering] = useState<ExposureSurface | null>(null);
  // Only worth a control when there is a choice: with the default alone, every
  // binding serves it and a picker would offer one option.
  const namedEnvironments = environments.filter((environment) => !environment.is_default);

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={2} />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("whereAgentAvailable")}</CardTitle>
        <CardDescription>
          {t("mentionableOnBoundBots")}
          {hasWorkspace && <> {t("approvalParksTheRun")}</>}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
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
                    aria-label={t("environmentOn", { bot: exposure.channel_bot_name })}
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
              <Button
                variant="ghost"
                size="sm"
                disabled={!canManage || setActive.isPending}
                aria-label={
                  exposure.is_active
                    ? t("pauseOn", { bot: exposure.channel_bot_name })
                    : t("resumeOn", { bot: exposure.channel_bot_name })
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
                aria-label={t("removeFrom", { bot: exposure.channel_bot_name })}
                onClick={() => revoke.mutate(exposure.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>

            {/* Under the row rather than behind a dialog: it is the one thing
                about a binding somebody actually wants to change after making
                it, and a surface's own instructions are worth reading beside
                the surface they belong to. */}
            {canManage && (
              <>
                {/* Under the binding, because that is what the answer belongs
                    to: the same agent on an internal Mattermost and a customer
                    Slack gets a different answer here, and a switch in the
                    Toolbox would have one for both. */}
                <ExposureCostReporting
                  exposureId={exposure.id}
                  value={exposure.usage_reporting}
                  disabled={setUsageReporting.isPending}
                  onChange={(usageReporting) =>
                    setUsageReporting.mutate({ exposureId: exposure.id, usageReporting })
                  }
                />
                <ExposureTools
                  exposureId={exposure.id}
                  platform={SURFACE_LABEL[exposure.surface]}
                  available={exposure.available_tools}
                  granted={exposure.tools}
                  disabled={setTools.isPending}
                  onChange={(tools) => setTools.mutate({ exposureId: exposure.id, tools })}
                />
                <ExposurePrompt
                  botName={exposure.channel_bot_name}
                  value={exposure.prompt}
                  variables={exposure.available_variables}
                  disabled={setPrompt.isPending}
                  onSave={(prompt) => setPrompt.mutate({ exposureId: exposure.id, prompt })}
                />
              </>
            )}
          </div>
        ))}

        {canManage && (
          <ExposureChannelTiles
            available={available}
            // A rule under the bindings; over nothing it would only underline the header.
            separated={exposures.length > 0}
            canRegister={canRegister}
            disabled={expose.isPending || createBot.isPending}
            onBind={(botId) => expose.mutate(botId)}
            onRegister={setRegistering}
          />
        )}
      </CardContent>
      {registering && (
        <AddChannelDialog
          open
          initialPlatform={registering}
          onOpenChange={(open) => !open && setRegistering(null)}
          // Registered from here, a bot is registered *for* this agent, so it
          // is bound straight away rather than left for a second click.
          onSubmit={async (bot) => {
            const created = await createBot.mutateAsync(bot);
            expose.mutate(created.id);
          }}
          isPending={createBot.isPending}
        />
      )}
    </Card>
  );
}
