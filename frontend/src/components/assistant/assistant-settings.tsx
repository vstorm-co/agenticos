"use client";

import { useState } from "react";
import Link from "next/link";
import { Bot, Building2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import { SectionCard } from "@/components/settings/settings-section";
import { Button, Label, Switch } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { useAssistant } from "@/hooks/use-assistant";
import { YourSuggestions } from "./your-suggestions";
import { YourWatches } from "./your-watches";
import { readPreferences, resetSilenced, setBubblesOff } from "@/lib/assistant-bubbles";
import { ROUTES } from "@/lib/constants";
import { useOrgStore } from "@/stores";

/**
 * Settings → Assistant (#2063): the reader's own tips.
 *
 * Nothing of the organization's is set here. The AI Architect is an agent like
 * any other, so its name, model and knowledge are edited in the Builder, and
 * whether the organization has it - and how it greets people - is on the
 * organization's page. Whoever may change those is pointed at both.
 */
export function AssistantSettings() {
  const t = useTranslations("assistantSettings");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { assistant, isLoading, error, retry } = useAssistant();
  if (isLoading) return <LoadingState variant="skeleton-panel" rows={4} />;
  if (error) {
    return (
      <ErrorState
        description={getErrorMessage(error, tErrors)}
        cta={{ label: tCommon("retry"), onClick: retry }}
      />
    );
  }
  if (!assistant) return null;
  return (
    <div className="space-y-6">
      {assistant.can_use ? (
        <YourTips />
      ) : (
        <p className="text-muted-foreground text-sm">{t("notForYou")}</p>
      )}
      {/* Not the Architect's: the platform's own look at the person's week, and
          theirs to switch off whoever runs the assistant (#2301). */}
      <YourSuggestions />
      <YourWatches />
      {assistant.can_configure && assistant.agent_id && (
        <WhereTheRestLives agentId={assistant.agent_id} />
      )}
    </div>
  );
}

function YourTips() {
  const t = useTranslations("assistantSettings");
  const [preferences, setPreferences] = useState(readPreferences);
  return (
    // A card like every other settings tab's section, not headings loose on
    // the page.
    <SectionCard title={t("yours")} description={t("yoursDescription")}>
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor="assistant-tips">{t("showTips")}</Label>
          <Switch
            id="assistant-tips"
            checked={!preferences.off}
            onCheckedChange={(on) => {
              setBubblesOff(!on);
              setPreferences(readPreferences());
            }}
          />
        </div>
        {preferences.silenced.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              resetSilenced();
              setPreferences(readPreferences());
            }}
          >
            {t("unsilence", { count: preferences.silenced.length })}
          </Button>
        )}
      </div>
    </SectionCard>
  );
}

function WhereTheRestLives({ agentId }: { agentId: string }) {
  const t = useTranslations("assistantSettings");
  const orgId = useOrgStore((state) => state.activeOrgId);
  return (
    <SectionCard title={t("organization")} description={t("organizationDescription")}>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" asChild>
          <Link href={ROUTES.AGENT_DETAIL(agentId)}>
            <Bot className="h-4 w-4" />
            {t("openBuilder")}
          </Link>
        </Button>
        {orgId && (
          <Button variant="outline" size="sm" asChild>
            <Link href={ROUTES.ORG_MEMBERS(orgId)}>
              <Building2 className="h-4 w-4" />
              {t("openOrganization")}
            </Link>
          </Button>
        )}
      </div>
    </SectionCard>
  );
}
