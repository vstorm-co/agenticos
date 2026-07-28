"use client";

import { useState } from "react";
import { Pause, Play, Plus, Trash2, Wallet } from "lucide-react";

import { LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useExposures } from "@/hooks";
import type { Exposure, ExposureSurface } from "@/types/exposures";

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
};

/**
 * How a cap reads when there is one, and when there is not.
 *
 * "No limit" rather than a blank: an empty cell next to a live binding reads as
 * "nothing to see", and the one thing worth noticing about a binding that can
 * spend without a ceiling is exactly that.
 */
function capLabel(exposure: Exposure): string {
  const parts: string[] = [];
  if (exposure.max_per_run_usd) parts.push(`$${exposure.max_per_run_usd} per conversation`);
  if (exposure.monthly_usd) parts.push(`$${exposure.monthly_usd} per month`);
  return parts.length ? parts.join(" · ") : "No spending limit";
}

/** An empty field clears the cap; anything else is sent as typed. */
function toLimit(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Where one agent is available.
 *
 * One section for every surface, not one per channel: an exposure is a single
 * concept, and splitting the UI by platform would be the first step towards
 * splitting the model by platform too.
 *
 * The empty state says what the absence means. An agent with no bindings is not
 * misconfigured — it is reachable from the dashboard and the API and nowhere
 * else, which is the default, and a bot that has stopped answering a handle it
 * used to answer is explained here rather than in a changelog.
 */
export function ExposuresPanel({ agentId, canManage }: ExposuresPanelProps) {
  const { exposures, isLoading, available, expose, setActive, setBudget, revoke } =
    useExposures(agentId);
  const [selectedBotId, setSelectedBotId] = useState("");
  const [editing, setEditing] = useState<string | null>(null);

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={2} />;

  function addExposure() {
    expose.mutate(selectedBotId);
    setSelectedBotId("");
  }

  function saveBudget(exposureId: string, form: HTMLFormElement) {
    const data = new FormData(form);
    setBudget.mutate({
      exposureId,
      budget: {
        max_per_run_usd: toLimit(String(data.get("max_per_run_usd") ?? "")),
        monthly_usd: toLimit(String(data.get("monthly_usd") ?? "")),
      },
    });
    setEditing(null);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Where this agent is available</CardTitle>
        <CardDescription>
          A published agent answers in the dashboard and through the API. To reach it from a chat
          platform, add the bot here — an agent is mentionable by <code>@handle</code> only on the
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
                  {SURFACE_LABEL[exposure.surface]} — {exposure.channel_bot_name}
                </p>
                <p className="text-muted-foreground text-xs">{capLabel(exposure)}</p>
                {!exposure.is_active && (
                  <p className="text-muted-foreground text-xs">
                    Paused — the handle answers nothing here.
                  </p>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={!canManage}
                aria-label={`Set spending limits for ${exposure.channel_bot_name}`}
                onClick={() => setEditing(editing === exposure.id ? null : exposure.id)}
              >
                <Wallet className="h-4 w-4" />
              </Button>
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

            {editing === exposure.id && (
              <form
                className="flex items-end gap-3 border-t pt-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  saveBudget(exposure.id, event.currentTarget);
                }}
              >
                <div className="flex-1 space-y-1">
                  <Label htmlFor={`per-run-${exposure.id}`}>Max per conversation (USD)</Label>
                  <Input
                    id={`per-run-${exposure.id}`}
                    name="max_per_run_usd"
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="No limit"
                    defaultValue={exposure.max_per_run_usd ?? ""}
                  />
                </div>
                <div className="flex-1 space-y-1">
                  <Label htmlFor={`monthly-${exposure.id}`}>Max per month (USD)</Label>
                  <Input
                    id={`monthly-${exposure.id}`}
                    name="monthly_usd"
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="No limit"
                    defaultValue={exposure.monthly_usd ?? ""}
                  />
                </div>
                <Button type="submit" disabled={setBudget.isPending}>
                  Save
                </Button>
              </form>
            )}
          </div>
        ))}

        {canManage && (
          <div className="flex items-end gap-3 border-t pt-3">
            <div className="flex-1 space-y-1">
              <Label htmlFor="exposure-bot">Add a channel</Label>
              <Select
                value={selectedBotId}
                disabled={available.length === 0}
                onValueChange={setSelectedBotId}
              >
                <SelectTrigger id="exposure-bot">
                  <SelectValue
                    placeholder={
                      available.length === 0
                        ? "No unbound bots in this organization"
                        : "Choose a bot"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {available.map((target) => (
                    <SelectItem key={target.id} value={target.id}>
                      {SURFACE_LABEL[target.platform]} — {target.name}
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
        )}
      </CardContent>
    </Card>
  );
}
