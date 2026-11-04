"use client";

import { useFormatter, useTranslations } from "next-intl";

import { FormField, Switch } from "@/components/ui";
import { usePublicLine } from "@/hooks/use-channel-bots";
import type { PublicLine, PublicLineReach } from "@/types/channels";

/** Each kind of reach holds the catalog key its sentence is written under. */
const REACH_KEY = {
  knowledge: "publicLineReachKnowledge",
  context: "publicLineReachContext",
  skills: "publicLineReachSkills",
  tables: "publicLineReachTables",
  web: "publicLineReachWeb",
  code: "publicLineReachCode",
  generation: "publicLineReachGeneration",
  delegates: "publicLineReachDelegates",
  mcp: "publicLineReachMcp",
  files: "publicLineReachFiles",
  voice: "publicLineReachVoice",
} as const satisfies Record<PublicLineReach["kind"], string>;

const REFUSED_KEY = {
  memory: "publicLineRefusedMemory",
  conversation_search: "publicLineRefusedConversationSearch",
  artifacts: "publicLineRefusedArtifacts",
  workflows: "publicLineRefusedWorkflows",
  background_tasks: "publicLineRefusedBackgroundTasks",
  platform_mcp: "publicLineRefusedPlatformMcp",
} as const satisfies Record<PublicLine["refused"][number], string>;

interface PublicLineFieldProps {
  botId: string;
  answers: boolean;
  files: boolean;
  onAnswers: (answers: boolean) => void;
  onFiles: (files: boolean) => void;
  /** The server's refusal of either choice, if it named one. */
  error?: string;
  filesError?: string;
}

/**
 * The switch that lets a WhatsApp bot answer people who never linked an account,
 * and the warning to read before turning it on.
 *
 * The warning comes from the server - what the served agent can reach, what bounds
 * its spending, the limits a customer meets - because the answer is the spec's, not
 * the console's. A line with no spending limit cannot be switched on, and says why;
 * one already on can always be switched off.
 */
export function PublicLineField({
  botId,
  answers,
  files,
  onAnswers,
  onFiles,
  error,
  filesError,
}: PublicLineFieldProps) {
  const t = useTranslations("pages.channels");
  const format = useFormatter();
  const { data: line } = usePublicLine(botId);
  const usd = (value: string) =>
    format.number(Number(value), { style: "currency", currency: "USD" });
  const names = (reach: PublicLineReach) => format.list(reach.names, { type: "conjunction" });

  return (
    <div className="space-y-3">
      <FormField
        label={t("publicLineSwitch")}
        htmlFor="edit-channel-public-line"
        description={t("publicLineHint")}
        error={error}
      >
        <Switch
          id="edit-channel-public-line"
          checked={answers}
          disabled={line === undefined || (!line.can_turn_on && !answers)}
          onCheckedChange={onAnswers}
        />
      </FormField>

      {line !== undefined && !line.can_turn_on && (
        <p className="text-destructive text-sm">{t("publicLineNoLimit")}</p>
      )}

      {line !== undefined && (
        <div className="bg-muted/40 space-y-2 rounded-md border p-3 text-sm">
          <p className="font-medium">
            {line.agent_name === null
              ? t("publicLineNoAgent")
              : t("publicLineServes", { agent: line.agent_name, version: line.agent_version ?? 0 })}
          </p>
          {line.reaches.length > 0 && (
            <>
              <p className="text-muted-foreground text-xs">{t("publicLineReaches")}</p>
              <ul className="list-disc space-y-1 pl-5">
                {line.reaches.map((reach) => (
                  <li key={reach.kind}>
                    {t(REACH_KEY[reach.kind], { names: names(reach) })}
                    {reach.detail !== null && (
                      <span className="text-muted-foreground"> ({reach.detail})</span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          <ul className="text-muted-foreground list-disc space-y-1 pl-5 text-xs">
            {line.agent_monthly_usd !== null && (
              <li>{t("publicLineAgentBudget", { amount: usd(line.agent_monthly_usd) })}</li>
            )}
            {line.organization_monthly_usd !== null && (
              <li>{t("publicLineOrgCap", { amount: usd(line.organization_monthly_usd) })}</li>
            )}
            <li>{t("publicLineRate", { count: line.rate_limit_rpm })}</li>
            <li>{t("publicLineApprovalExpiry", { hours: line.approval_expiry_hours })}</li>
            <li>{t("publicLineFileCap", { mb: line.file_max_mb })}</li>
            {line.voice === "on" && (
              <li>{t("publicLineVoiceCap", { mb: line.recording_max_mb })}</li>
            )}
            {line.voice === "refused_no_org_cap" && <li>{t("publicLineVoiceNeedsCap")}</li>}
          </ul>
          <p className="text-muted-foreground text-xs">
            {t("publicLineRefused", {
              list: format.list(
                line.refused.map((kind) => t(REFUSED_KEY[kind])),
                { type: "conjunction" },
              ),
            })}
          </p>
        </div>
      )}

      <FormField
        label={t("publicLineFiles")}
        htmlFor="edit-channel-customer-files"
        description={t("publicLineFilesHint")}
        error={filesError}
      >
        <Switch
          id="edit-channel-customer-files"
          checked={files}
          disabled={!answers}
          onCheckedChange={onFiles}
        />
      </FormField>
    </div>
  );
}
