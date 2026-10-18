"use client";

import { useState } from "react";
import Link from "next/link";
import { Bot } from "lucide-react";
import { useTranslations } from "next-intl";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button, FormField, Switch, Textarea } from "@/components/ui";
import { useAssistant, useUpdateAssistant } from "@/hooks/use-assistant";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores";
import type { AssistantState } from "@/types/assistant";

/**
 * Whether this organization has its AI Architect, and how it greets people (#2063).
 *
 * Only what the organization decides about it as its assistant. The Architect is
 * an agent like any other, so its name, model and knowledge are edited in the
 * Builder, which the card links to rather than repeating.
 *
 * `/assistant` answers for the active organization, so the card is drawn only on
 * that organization's page - and only for somebody who may change it, like the
 * spending limit beside it.
 */
export function OrgAssistant({ orgId }: { orgId: string }) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { assistant } = useAssistant();
  if (orgId !== activeOrgId || !assistant?.can_configure || !assistant.agent_id) return null;
  return <AssistantCard assistant={assistant} agentId={assistant.agent_id} />;
}

function AssistantCard({ assistant, agentId }: { assistant: AssistantState; agentId: string }) {
  const t = useTranslations("orgAssistant");
  const update = useUpdateAssistant();
  const [greeting, setGreeting] = useState(assistant.greeting ?? "");
  const dirty = greeting !== (assistant.greeting ?? "");

  return (
    <div data-tour="org-assistant">
      <SettingsSection title={t("title")} description={t("description")}>
        <div className="space-y-5">
          <label className="flex items-start gap-3">
            <Switch
              checked={assistant.status !== "disabled"}
              disabled={update.isPending}
              onCheckedChange={(on) => update.mutate({ enabled: on })}
              aria-label={t("enabled")}
            />
            <span className="text-muted-foreground text-xs leading-relaxed">
              {t("enabledHint")}
            </span>
          </label>
          {assistant.status === "needs_model" && (
            <p className="text-muted-foreground text-sm">{t("needsModel")}</p>
          )}
          <FormField
            label={t("greeting")}
            htmlFor="org-assistant-greeting"
            description={t("greetingHint")}
          >
            <Textarea
              id="org-assistant-greeting"
              value={greeting}
              rows={3}
              maxLength={500}
              onChange={(e) => setGreeting(e.target.value)}
            />
          </FormField>
          {/* Beside Save rather than in the header, where it squeezed the
              description into a column on a phone. */}
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={!dirty || update.isPending}
              onClick={() => update.mutate({ greeting: greeting.trim() || null })}
            >
              {t("save")}
            </Button>
            <Button variant="outline" asChild>
              <Link href={ROUTES.AGENT_DETAIL(agentId)}>
                <Bot className="h-4 w-4" />
                {t("openBuilder")}
              </Link>
            </Button>
          </div>
        </div>
      </SettingsSection>
    </div>
  );
}
