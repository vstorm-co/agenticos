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
import type { ExposureSurface } from "@/types/exposures";

interface ExposuresPanelProps {
  agentId: string;
  /**
   * Where an agent is available is the same class of decision as what it runs,
   * so the server demands `agents:publish` on this agent. The caller passes the
   * answer in rather than this panel re-deriving it, for the same reason the
   * sharing panel does.
   */
  canManage: boolean;
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

export function ExposuresPanel({ agentId, canManage }: ExposuresPanelProps) {
  const { exposures, isLoading, available, expose, setActive, setEnvironment, revoke } =
    useExposures(agentId);
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
        <CardTitle>Where this agent is available</CardTitle>
        <CardDescription>
          A published agent answers in the dashboard and through the API. To reach it from a chat
          platform, add the bot here - an agent is mentionable by <code>@handle</code> only on the
          bots it is bound to.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {exposures.length === 0 && (
          <p className="text-muted-foreground text-sm">Not available on any channel yet.</p>
        )}

        {exposures.map((exposure) => (
          <div key={exposure.id} className="space-y-3 rounded-md border p-3">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {SURFACE_LABEL[exposure.surface]} - {exposure.channel_bot_name}
                </p>
                {!exposure.is_active && (
                  <p className="text-muted-foreground text-xs">
                    Paused - the handle answers nothing here.
                  </p>
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
                    <SelectItem value={DEFAULT_ENV}>default</SelectItem>
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
                <Label htmlFor="exposure-bot">Add a channel</Label>
                <Select value={selectedBotId} onValueChange={setSelectedBotId}>
                  <SelectTrigger id="exposure-bot">
                    <SelectValue placeholder="Choose a bot" />
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
                Add
              </Button>
            </div>
          ) : (
            // A disabled picker here was a dead end: it said no bot could be
            // chosen without saying which of the two absences this is - no
            // bots at all, or all of them already bound.
            <p className="text-muted-foreground border-t pt-3 text-sm">
              {exposures.length > 0
                ? "This agent is already on every bot this organization has registered."
                : "This organization has no channel bots yet. Register one in the panel below, then bind it here."}
            </p>
          ))}
      </CardContent>
    </Card>
  );
}
