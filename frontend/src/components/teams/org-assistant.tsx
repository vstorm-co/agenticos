"use client";

import { Bot } from "lucide-react";
import { useTranslations } from "next-intl";

import { SetupIndicator } from "@/components/settings/setup-indicator";
import { architectSetupHints } from "@/lib/setup-hints";
import { ServiceCard } from "@/components/settings/service-card";
import { Switch } from "@/components/ui";
import { useAssistant, useUpdateAssistant } from "@/hooks/use-assistant";
import { useOrgStore } from "@/stores";
import type { AssistantState } from "@/types/assistant";

/**
 * Whether this organization has its AI Architect (#2063).
 *
 * Only what the organization decides about it as its assistant. The Architect is
 * an agent like any other, so its name, model and knowledge are edited in the
 * Builder; this card controls only organization availability.
 *
 * `/assistant` answers for the active organization, so the card is drawn only on
 * that organization's page - and only for somebody who may change it, like the
 * spending limit beside it.
 */
export function OrgAssistant({ orgId }: { orgId: string }) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { assistant } = useAssistant();
  if (orgId !== activeOrgId || !assistant?.can_configure || !assistant.agent_id) return null;
  return <AssistantCard assistant={assistant} />;
}

function AssistantCard({ assistant }: { assistant: AssistantState }) {
  const t = useTranslations("orgAssistant");
  const update = useUpdateAssistant();

  return (
    <div data-tour="org-assistant">
      <ServiceCard
        icon={Bot}
        action={
          <Switch
            checked={assistant.status !== "disabled"}
            disabled={update.isPending}
            onCheckedChange={(on) => update.mutate({ enabled: on })}
            aria-label={t("enabled")}
          />
        }
        status={<SetupIndicator hints={architectSetupHints(assistant)} />}
        title={t("title")}
        description={t("description")}
      >
        {assistant.status === "needs_model" && (
          <p className="text-muted-foreground text-sm">{t("needsModel")}</p>
        )}
      </ServiceCard>
    </div>
  );
}
