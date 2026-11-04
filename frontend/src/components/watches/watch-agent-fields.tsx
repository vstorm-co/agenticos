"use client";

import { RoutineOptions } from "@/components/triggers/routine-options";
import { AgentAvatar } from "@/components/agents/agent-avatar";

import { ErrorState } from "@/components/states/error-state";
import { useTranslations } from "next-intl";

import { DEFAULT_ENV, EnvironmentField } from "@/components/triggers/environment-field";
import { VersionField } from "@/components/triggers/version-field";
import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgentEnvironments, useAgents } from "@/hooks";

export function WatchAgentFields({
  agentId,
  environmentId,
  pinnedVersionId,
  onAgent,
  onEnvironment,
  onVersion,
  onVersionValid,
  versionValid,
  disabled,
  error,
}: {
  agentId: string;
  environmentId: string | null;
  pinnedVersionId: string | null;
  onAgent: (id: string) => void;
  onEnvironment: (id: string | null) => void;
  onVersion: (id: string | null) => void;
  onVersionValid: (valid: boolean) => void;
  versionValid: boolean;
  disabled: boolean;
  error?: string;
}) {
  const t = useTranslations("watches");
  const { agents, isLoading, error: agentsError, refetch: refetchAgents } = useAgents();
  const tUi = useTranslations("common");
  const {
    environments,
    error: environmentsError,
    refetch: refetchEnvironments,
  } = useAgentEnvironments(agentId || null);
  const runnable = agents.filter((agent) => agent.can_run && agent.current_version_id);
  return (
    <div className="space-y-4">
      {agentsError && (
        <ErrorState cta={{ label: tUi("retry"), onClick: () => void refetchAgents() }} />
      )}
      <FormField
        label={t("agent")}
        htmlFor="watch-agent"
        description={t("approvedSourcesHint")}
        error={error}
      >
        <Select value={agentId} onValueChange={onAgent} disabled={disabled || isLoading}>
          <SelectTrigger id="watch-agent">
            <SelectValue placeholder={t("agentPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {agentId && !runnable.some((agent) => agent.id === agentId) && (
              <SelectItem value={agentId} disabled>
                {t("unavailableAgent")}
              </SelectItem>
            )}
            {runnable.map((agent) => (
              <SelectItem key={agent.id} value={agent.id} textValue={agent.name}>
                <span className="flex min-w-0 items-center gap-2.5">
                  <AgentAvatar
                    agentId={agent.id}
                    slug={agent.slug}
                    hasAvatar={agent.has_avatar}
                    colorSlot={agent.avatar_color}
                    size="sm"
                  />
                  <span className="truncate">{agent.name}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      {agentId && (
        <RoutineOptions invalid={!versionValid || Boolean(error) || Boolean(environmentsError)}>
          {environmentsError && (
            <ErrorState cta={{ label: tUi("retry"), onClick: () => void refetchEnvironments() }} />
          )}
          <EnvironmentField
            value={environmentId ?? DEFAULT_ENV}
            onChange={(id) => onEnvironment(id === DEFAULT_ENV ? null : id)}
            environments={environments.filter((env) => !env.is_default)}
            defaultEnvironment={environments.find((env) => env.is_default) ?? null}
            id="watch-environment"
          />
          {environmentId === null && (
            <VersionField
              key={agentId}
              agentId={agentId}
              value={pinnedVersionId}
              onChange={onVersion}
              onValidChange={onVersionValid}
            />
          )}
        </RoutineOptions>
      )}
    </div>
  );
}
